import datetime as dt
import math
from typing import Any

from fastapi import HTTPException
from sqlalchemy.orm import Session

from backend.config import settings
from backend.models import Driver, Ride, Trip
from backend.redis_client import get_redis_client
from backend.services.ride_timeout_service import is_ride_request_timed_out
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


def _redis_driver_meta_key(driver_id: str) -> str:
    return f"driver_meta:{driver_id}"


def _redis_driver_loc_key(driver_id: str) -> str:
    return f"driver_loc:{driver_id}"


def _cache_driver_meta(driver: Driver):
    redis_client = get_redis_client()
    if not redis_client:
        return

    mapping = {
        "tenant_id": driver.tenant_id,
        "region": driver.region,
        "vehicle_tier": driver.vehicle_tier,
        "status": driver.status,
        "is_online": "1" if driver.is_online else "0",
    }

    pipe = redis_client.pipeline()
    pipe.hset(_redis_driver_meta_key(driver.id), mapping=mapping)
    pipe.expire(_redis_driver_meta_key(driver.id), settings.driver_meta_ttl_sec)

    if driver.lat is not None and driver.lng is not None:
        pipe.hset(_redis_driver_loc_key(driver.id), mapping={"lat": str(driver.lat), "lng": str(driver.lng)})
        pipe.expire(_redis_driver_loc_key(driver.id), settings.driver_meta_ttl_sec)
        geo_key = _redis_geo_key(driver.tenant_id, driver.region, driver.vehicle_tier)
        if driver.is_online and driver.status == "available":
            pipe.geoadd(geo_key, (float(driver.lng), float(driver.lat), driver.id))
            pipe.expire(geo_key, settings.driver_meta_ttl_sec)
        else:
            pipe.zrem(geo_key, driver.id)

    pipe.execute()


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
    _cache_driver_meta(driver)
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

    redis_client = get_redis_client()
    if redis_client:
        pipe = redis_client.pipeline()
        pipe.hset(_redis_driver_meta_key(driver.id), mapping={"status": "offline", "is_online": "0"})
        pipe.expire(_redis_driver_meta_key(driver.id), settings.driver_meta_ttl_sec)
        pipe.zrem(_redis_geo_key(driver.tenant_id, driver.region, driver.vehicle_tier), driver.id)
        pipe.execute()

    return driver


def upsert_driver_location(db: Session, driver_id: str, tenant_id: str, region: str, lat: float, lng: float) -> dict[str, Any]:
    redis_client = get_redis_client()
    now = dt.datetime.utcnow()

    # Hot path: Redis-first location write for very high update throughput.
    if redis_client:
        meta_key = _redis_driver_meta_key(driver_id)
        meta = redis_client.hgetall(meta_key)
        if meta:
            if meta.get("tenant_id") != tenant_id or meta.get("region") != region:
                raise HTTPException(status_code=400, detail="Driver tenant/region mismatch")

            vehicle_tier = meta.get("vehicle_tier", "mini")
            status = meta.get("status", "available")
            if status == "offline":
                status = "available"

            pipe = redis_client.pipeline()
            pipe.hset(meta_key, mapping={"status": status, "is_online": "1"})
            pipe.expire(meta_key, settings.driver_meta_ttl_sec)
            pipe.hset(_redis_driver_loc_key(driver_id), mapping={"lat": str(lat), "lng": str(lng)})
            pipe.expire(_redis_driver_loc_key(driver_id), settings.driver_meta_ttl_sec)
            pipe.geoadd(_redis_geo_key(tenant_id, region, vehicle_tier), (lng, lat, driver_id))
            pipe.expire(_redis_geo_key(tenant_id, region, vehicle_tier), settings.driver_meta_ttl_sec)
            pipe.execute()

            # Write-behind throttle: sync operational DB once per interval per driver.
            sync_key = f"driver_dbsync:{driver_id}"
            should_sync = redis_client.set(sync_key, "1", ex=settings.location_db_sync_interval_sec, nx=True)
            if should_sync:
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
                driver.last_seen_at = now
                db.commit()
                status = driver.status

            return {
                "id": driver_id,
                "tenant_id": tenant_id,
                "region": region,
                "status": status,
                "lat": lat,
                "lng": lng,
                "last_seen_at": now.isoformat(),
            }

    # Fallback path: DB-first.
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
    driver.last_seen_at = now
    db.commit()
    db.refresh(driver)
    _cache_driver_meta(driver)

    return {
        "id": driver.id,
        "tenant_id": driver.tenant_id,
        "region": driver.region,
        "status": driver.status,
        "lat": driver.lat,
        "lng": driver.lng,
        "last_seen_at": driver.last_seen_at.isoformat(),
    }


def _candidate_driver_ids(db: Session, ride: Ride, exclude_driver_ids: set[str] | None = None) -> list[tuple[str, float]]:
    redis_client = get_redis_client()
    candidates: list[tuple[str, float]] = []
    exclude_driver_ids = exclude_driver_ids or set()

    if redis_client:
        key = _redis_geo_key(ride.tenant_id, ride.region, ride.tier)
        nearby = redis_client.georadius(
            key,
            ride.pickup_lng,
            ride.pickup_lat,
            settings.default_search_radius_km,
            unit="km",
            count=settings.dispatch_candidate_pool_size,
            sort="ASC",
            withdist=True,
        )
        for member, distance in nearby or []:
            driver_id = str(member)
            if driver_id in exclude_driver_ids:
                continue
            meta = redis_client.hgetall(_redis_driver_meta_key(driver_id))
            if not meta:
                continue
            if meta.get("tenant_id") != ride.tenant_id or meta.get("region") != ride.region:
                continue
            if meta.get("vehicle_tier") != ride.tier:
                continue
            if meta.get("status") != "available":
                continue
            if meta.get("is_online") != "1":
                continue
            candidates.append((driver_id, float(distance)))

    if candidates:
        return candidates

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
        .limit(settings.dispatch_candidate_pool_size)
        .all()
    )
    for driver in rows:
        if driver.id in exclude_driver_ids:
            continue
        distance = haversine_km(ride.pickup_lat, ride.pickup_lng, float(driver.lat), float(driver.lng))
        if distance <= settings.default_search_radius_km:
            candidates.append((driver.id, distance))

    return sorted(candidates, key=lambda item: item[1])


def assign_driver_to_ride(db: Session, ride: Ride, exclude_driver_ids: set[str] | None = None) -> dict[str, Any]:
    if is_ride_request_timed_out(ride):
        ride.status = "expired"
        db.commit()
        return {"assigned": False, "reason": "No driver found within timeout window"}

    if ride.status not in {"requested"}:
        return {"assigned": False, "reason": f"Ride status is {ride.status}"}

    for candidate_driver_id, distance in _candidate_driver_ids(db, ride, exclude_driver_ids=exclude_driver_ids):
        driver = db.query(Driver).filter(Driver.id == candidate_driver_id).with_for_update().first()
        ride_locked = db.query(Ride).filter(Ride.id == ride.id).with_for_update().first()
        if not driver or not ride_locked:
            continue
        if ride_locked.status != "requested":
            db.rollback()
            return {"assigned": False, "reason": f"Ride status changed to {ride_locked.status}"}
        if driver.status != "available" or not driver.is_online:
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
        _cache_driver_meta(driver)
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
    _cache_driver_meta(driver)

    reassignment = assign_driver_to_ride(db, ride, exclude_driver_ids={driver_id})
    return {
        "declined_driver_id": driver_id,
        "ride_id": ride_id,
        "reassignment": reassignment,
    }
