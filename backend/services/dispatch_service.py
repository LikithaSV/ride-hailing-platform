import math
from typing import Any

from fastapi import HTTPException
from sqlalchemy.orm import Session

from backend.config import settings
from backend.models import Driver, Ride, Trip
from backend.redis_client import get_redis_client
from backend.utils.state_machine import RIDE_TRANSITIONS, transition


def haversine_km(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    radius = 6371.0
    d_lat = math.radians(lat2 - lat1)
    d_lng = math.radians(lng2 - lng1)
    a = math.sin(d_lat / 2) ** 2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(d_lng / 2) ** 2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return radius * c


def _redis_geo_key(tenant_id: str, region: str, tier: str) -> str:
    return f"drivers_geo:{tenant_id}:{region}:{tier}"


def update_driver_location_index(driver: Driver):
    if driver.lat is None or driver.lng is None:
        return
    redis_client = get_redis_client()
    if not redis_client:
        return
    key = _redis_geo_key(driver.tenant_id, driver.region, driver.vehicle_tier)
    redis_client.geoadd(key, (driver.lng, driver.lat, driver.id))


def register_driver(db: Session, driver_id: str, tenant_id: str, region: str, vehicle_tier: str) -> Driver:
    driver = db.query(Driver).filter(Driver.id == driver_id).first()
    if driver:
        driver.tenant_id = tenant_id
        driver.region = region
        driver.vehicle_tier = vehicle_tier
        driver.status = "available"
        driver.is_online = True
    else:
        driver = Driver(
            id=driver_id,
            tenant_id=tenant_id,
            region=region,
            vehicle_tier=vehicle_tier,
            status="available",
            is_online=True,
        )
        db.add(driver)
    db.commit()
    db.refresh(driver)
    return driver


def set_driver_offline(db: Session, driver_id: str, tenant_id: str, region: str) -> Driver:
    driver = db.query(Driver).filter(Driver.id == driver_id).with_for_update().first()
    if not driver:
        raise HTTPException(status_code=404, detail="Driver not found")
    if driver.tenant_id != tenant_id or driver.region != region:
        raise HTTPException(status_code=400, detail="Driver tenant/region mismatch")

    if driver.status == "on_trip":
        raise HTTPException(status_code=409, detail="Driver cannot go offline during active trip")

    driver.is_online = False
    driver.status = "offline"
    db.commit()
    db.refresh(driver)
    return driver


def upsert_driver_location(db: Session, driver_id: str, tenant_id: str, region: str, lat: float, lng: float) -> Driver:
    driver = db.query(Driver).filter(Driver.id == driver_id).first()
    if not driver:
        raise HTTPException(status_code=404, detail="Driver not found; register driver first")

    if driver.tenant_id != tenant_id or driver.region != region:
        raise HTTPException(status_code=400, detail="Driver tenant/region mismatch")

    driver.lat = lat
    driver.lng = lng
    driver.is_online = True
    if driver.status == "offline":
        driver.status = "available"
    db.commit()
    db.refresh(driver)
    update_driver_location_index(driver)
    return driver


def _candidate_drivers(db: Session, ride: Ride, exclude_driver_ids: set[str] | None = None) -> list[tuple[Driver, float]]:
    redis_client = get_redis_client()
    candidates: list[tuple[Driver, float]] = []
    exclude_driver_ids = exclude_driver_ids or set()

    if redis_client:
        key = _redis_geo_key(ride.tenant_id, ride.region, ride.tier)
        nearby_ids = redis_client.georadius(key, ride.pickup_lng, ride.pickup_lat, settings.default_search_radius_km, unit="km", count=20)
        if nearby_ids:
            nearby_ids = [d for d in nearby_ids if d not in exclude_driver_ids]
            driver_rows = (
                db.query(Driver)
                .filter(
                    Driver.id.in_(nearby_ids),
                    Driver.status == "available",
                    Driver.is_online.is_(True),
                    Driver.tenant_id == ride.tenant_id,
                    Driver.region == ride.region,
                    Driver.vehicle_tier == ride.tier,
                )
                .all()
            )
            for d in driver_rows:
                if d.lat is None or d.lng is None:
                    continue
                candidates.append((d, haversine_km(ride.pickup_lat, ride.pickup_lng, d.lat, d.lng)))

    if candidates:
        return sorted(candidates, key=lambda c: c[1])

    rows = (
        db.query(Driver)
        .filter(
            Driver.tenant_id == ride.tenant_id,
            Driver.region == ride.region,
            Driver.vehicle_tier == ride.tier,
            Driver.status == "available",
            Driver.is_online.is_(True),
            Driver.lat.is_not(None),
            Driver.lng.is_not(None),
        )
        .limit(200)
        .all()
    )
    for d in rows:
        if d.id in exclude_driver_ids:
            continue
        distance = haversine_km(ride.pickup_lat, ride.pickup_lng, float(d.lat), float(d.lng))
        if distance <= settings.default_search_radius_km:
            candidates.append((d, distance))

    return sorted(candidates, key=lambda c: c[1])


def assign_driver_to_ride(db: Session, ride: Ride, exclude_driver_ids: set[str] | None = None) -> dict[str, Any]:
    if ride.status not in {"requested"}:
        return {"assigned": False, "reason": f"Ride status is {ride.status}"}

    for candidate, distance in _candidate_drivers(db, ride, exclude_driver_ids=exclude_driver_ids):
        driver = db.query(Driver).filter(Driver.id == candidate.id).with_for_update().first()
        ride_locked = db.query(Ride).filter(Ride.id == ride.id).with_for_update().first()
        if not driver or not ride_locked:
            continue
        if ride_locked.status != "requested":
            db.rollback()
            return {"assigned": False, "reason": f"Ride status changed to {ride_locked.status}"}
        if driver.status != "available":
            db.rollback()
            continue

        transition(ride_locked.status, "accepted", RIDE_TRANSITIONS, "ride")
        ride_locked.status = "accepted"
        ride_locked.assigned_driver_id = driver.id
        driver.status = "on_trip"

        trip = db.query(Trip).filter(Trip.ride_id == ride_locked.id).with_for_update().first()
        if trip:
            trip.driver_id = driver.id
            trip.status = "created"
        else:
            trip = Trip(
                tenant_id=ride_locked.tenant_id,
                region=ride_locked.region,
                ride_id=ride_locked.id,
                driver_id=driver.id,
                rider_id=ride_locked.rider_id,
                status="created",
            )
            db.add(trip)

        db.commit()
        db.refresh(ride_locked)
        db.refresh(trip)
        return {
            "assigned": True,
            "driver_id": driver.id,
            "distance_km": round(distance, 3),
            "trip_id": trip.id,
            "ride_status": ride_locked.status,
        }

    db.rollback()
    return {"assigned": False, "reason": "No nearby driver available"}


def driver_decline_ride(db: Session, tenant_id: str, region: str, driver_id: str, ride_id: str) -> dict[str, Any]:
    driver = db.query(Driver).filter(Driver.id == driver_id).with_for_update().first()
    ride = db.query(Ride).filter(Ride.id == ride_id).with_for_update().first()
    if not driver or not ride:
        raise HTTPException(status_code=404, detail="Driver or ride not found")

    if driver.tenant_id != tenant_id or ride.tenant_id != tenant_id:
        raise HTTPException(status_code=400, detail="Tenant mismatch")
    if driver.region != region or ride.region != region:
        raise HTTPException(status_code=400, detail="Region mismatch")
    if ride.assigned_driver_id != driver_id:
        raise HTTPException(status_code=409, detail="Ride is not assigned to this driver")

    trip = db.query(Trip).filter(Trip.ride_id == ride.id).with_for_update().first()
    if trip and trip.status != "created":
        raise HTTPException(status_code=409, detail="Driver can decline only before trip starts")

    transition(ride.status, "requested", RIDE_TRANSITIONS, "ride")
    ride.status = "requested"
    ride.assigned_driver_id = None
    driver.status = "available"
    if trip:
        db.delete(trip)

    db.commit()
    db.refresh(ride)

    reassignment = assign_driver_to_ride(db, ride, exclude_driver_ids={driver_id})
    return {
        "declined_driver_id": driver_id,
        "ride_id": ride_id,
        "reassignment": reassignment,
    }
