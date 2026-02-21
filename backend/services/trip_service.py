import datetime as dt

from fastapi import HTTPException
from sqlalchemy.orm import Session

from backend.models import Driver, Ride, Trip
from backend.services.dispatch_service import haversine_km
from backend.services.surge_service import fare_estimate_km_based
from backend.utils.state_machine import RIDE_TRANSITIONS, TRIP_TRANSITIONS, transition


def _expected_duration_sec(distance_km: float) -> int:
    avg_speed_kmph = 24.0
    return max(300, int((distance_km / avg_speed_kmph) * 3600))


def start_trip(db: Session, tenant_id: str, region: str, trip_id: str) -> Trip:
    trip = db.query(Trip).filter(Trip.id == trip_id).with_for_update().first()
    if not trip:
        raise HTTPException(status_code=404, detail="Trip not found")
    if trip.tenant_id != tenant_id or trip.region != region:
        raise HTTPException(status_code=400, detail="Tenant/region mismatch")

    transition(trip.status, "in_progress", TRIP_TRANSITIONS, "trip")
    trip.status = "in_progress"
    trip.started_at = trip.started_at or dt.datetime.utcnow()

    ride = db.query(Ride).filter(Ride.id == trip.ride_id).with_for_update().first()
    if not ride:
        raise HTTPException(status_code=404, detail="Linked ride not found")
    transition(ride.status, "trip_started", RIDE_TRANSITIONS, "ride")
    ride.status = "trip_started"

    db.commit()
    db.refresh(trip)
    return trip


def end_trip(db: Session, tenant_id: str, region: str, trip_id: str) -> tuple[Trip, Ride]:
    trip = db.query(Trip).filter(Trip.id == trip_id).with_for_update().first()
    if not trip:
        raise HTTPException(status_code=404, detail="Trip not found")
    if trip.tenant_id != tenant_id or trip.region != region:
        raise HTTPException(status_code=400, detail="Tenant/region mismatch")

    transition(trip.status, "ended", TRIP_TRANSITIONS, "trip")

    ride = db.query(Ride).filter(Ride.id == trip.ride_id).with_for_update().first()
    if not ride:
        raise HTTPException(status_code=404, detail="Linked ride not found")

    distance_km = haversine_km(ride.pickup_lat, ride.pickup_lng, ride.destination_lat, ride.destination_lng)
    expected_duration = _expected_duration_sec(distance_km)

    ended_at = dt.datetime.utcnow()
    if trip.started_at:
        actual_duration = int((ended_at - trip.started_at).total_seconds())
        duration_sec = max(120, min(actual_duration, expected_duration * 2))
    else:
        duration_sec = expected_duration

    trip.status = "ended"
    trip.ended_at = ended_at
    trip.distance_km = round(distance_km, 2)
    trip.duration_sec = duration_sec

    fare = fare_estimate_km_based(distance_km=trip.distance_km, duration_sec=trip.duration_sec, surge_multiplier=ride.surge_multiplier)
    trip.fare_amount = fare
    ride.final_fare = fare

    transition(ride.status, "trip_completed", RIDE_TRANSITIONS, "ride")
    ride.status = "trip_completed"

    driver = db.query(Driver).filter(Driver.id == trip.driver_id).with_for_update().first()
    if driver:
        driver.status = "available"

    db.commit()
    db.refresh(trip)
    db.refresh(ride)
    return trip, ride
