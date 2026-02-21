from fastapi import APIRouter, Depends, Header
from sqlalchemy.orm import Session

from backend.db import get_db
from backend.events import event_bus
from backend.idempotency import require_idempotency_key, run_idempotent
from backend.models import Trip
from backend.schemas import TripActionRequest, TripEndRequest
from backend.services.trip_service import end_trip, start_trip
from backend.utils.region_guard import ensure_region_local

router = APIRouter(prefix="/trips", tags=["trips"])


@router.post("/{trip_id}/start")
async def start_trip_endpoint(
    trip_id: str,
    request: TripActionRequest,
    db: Session = Depends(get_db),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    require_idempotency_key(idempotency_key)
    ensure_region_local(request.region)

    def _action():
        trip = start_trip(db, tenant_id=request.tenant_id, region=request.region, trip_id=trip_id)
        return 200, {"trip_id": trip.id, "status": trip.status, "started_at": trip.started_at.isoformat() if trip.started_at else None}

    status, body = run_idempotent(db, request.tenant_id, f"POST:/trips/{trip_id}/start", idempotency_key, _action)
    await event_bus.publish(request.tenant_id, "trip.started", body)
    return body


@router.post("/{trip_id}/end")
async def end_trip_endpoint(
    trip_id: str,
    request: TripEndRequest,
    db: Session = Depends(get_db),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    require_idempotency_key(idempotency_key)
    ensure_region_local(request.region)

    def _action():
        trip, ride = end_trip(
            db,
            tenant_id=request.tenant_id,
            region=request.region,
            trip_id=trip_id,
        )
        return 200, {
            "trip_id": trip.id,
            "trip_status": trip.status,
            "ride_id": ride.id,
            "ride_status": ride.status,
            "distance_km": trip.distance_km,
            "duration_sec": trip.duration_sec,
            "fare": trip.fare_amount,
        }

    status, body = run_idempotent(db, request.tenant_id, f"POST:/trips/{trip_id}/end", idempotency_key, _action)
    await event_bus.publish(request.tenant_id, "trip.ended", body)
    return body


@router.get("/{trip_id}")
def get_trip(trip_id: str, tenant_id: str, db: Session = Depends(get_db)):
    trip = db.query(Trip).filter(Trip.id == trip_id, Trip.tenant_id == tenant_id).first()
    if not trip:
        return {"detail": "Trip not found"}
    return {
        "id": trip.id,
        "ride_id": trip.ride_id,
        "driver_id": trip.driver_id,
        "status": trip.status,
        "distance_km": trip.distance_km,
        "duration_sec": trip.duration_sec,
        "fare_amount": trip.fare_amount,
        "started_at": trip.started_at.isoformat() if trip.started_at else None,
        "ended_at": trip.ended_at.isoformat() if trip.ended_at else None,
    }
