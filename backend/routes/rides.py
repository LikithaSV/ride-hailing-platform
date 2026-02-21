from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy.orm import Session

from backend.db import get_db
from backend.events import event_bus
from backend.idempotency import require_idempotency_key, run_idempotent
from backend.models import Driver, Ride
from backend.redis_client import cached_json, get_redis_client
from backend.schemas import RideCreateRequest, RideEstimateRequest
from backend.services.dispatch_service import assign_driver_to_ride, haversine_km
from backend.services.ride_timeout_service import expire_stale_requested_rides, is_ride_request_timed_out
from backend.services.surge_service import fare_estimate_km_based, get_surge_multiplier
from backend.utils.region_guard import ensure_region_local

router = APIRouter(prefix="/rides", tags=["rides"])


def _redis_geo_key(tenant_id: str, region: str, tier: str) -> str:
    return f"drivers_geo:{tenant_id}:{region}:{tier}"


@router.post("/estimate")
def estimate_ride(request: RideEstimateRequest, db: Session = Depends(get_db)):
    ensure_region_local(request.region)
    expire_stale_requested_rides(db, tenant_id=request.tenant_id, region=request.region, tier=request.tier)
    surge = get_surge_multiplier(db, request.tenant_id, request.region, request.tier)
    distance_km = haversine_km(request.pickup_lat, request.pickup_lng, request.destination_lat, request.destination_lng)
    duration_sec = max(300, int((distance_km / 24.0) * 3600))

    base_fare = fare_estimate_km_based(distance_km=distance_km, duration_sec=duration_sec, surge_multiplier=1.0)
    surged_fare = fare_estimate_km_based(distance_km=distance_km, duration_sec=duration_sec, surge_multiplier=surge)

    active_requests = (
        db.query(Ride)
        .filter(Ride.tenant_id == request.tenant_id, Ride.region == request.region, Ride.tier == request.tier, Ride.status.in_(["requested", "accepted"]))
        .count()
    )
    redis_client = get_redis_client()
    if redis_client:
        available_drivers = int(redis_client.zcard(_redis_geo_key(request.tenant_id, request.region, request.tier)) or 0)
    else:
        available_drivers = (
            db.query(Driver)
            .filter(
                Driver.tenant_id == request.tenant_id,
                Driver.region == request.region,
                Driver.vehicle_tier == request.tier,
                Driver.status == "available",
                Driver.is_online.is_(True),
            )
            .count()
        )

    return {
        "tenant_id": request.tenant_id,
        "region": request.region,
        "tier": request.tier,
        "distance_km": round(distance_km, 2),
        "eta_min": round(duration_sec / 60.0),
        "surge_multiplier": surge,
        "fare_without_surge": base_fare,
        "estimated_fare": surged_fare,
        "surge_explanation": {
            "active_requests": active_requests,
            "available_drivers": available_drivers,
            "reason": "Surge increases when active requests are high relative to available drivers.",
        },
    }


@router.post("")
async def create_ride(
    request: RideCreateRequest,
    db: Session = Depends(get_db),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    require_idempotency_key(idempotency_key)
    ensure_region_local(request.region)

    def _action():
        expire_stale_requested_rides(db, tenant_id=request.tenant_id, region=request.region, tier=request.tier)
        surge = get_surge_multiplier(db, request.tenant_id, request.region, request.tier)
        distance_km = haversine_km(request.pickup_lat, request.pickup_lng, request.destination_lat, request.destination_lng)
        duration_sec = max(300, int((distance_km / 24.0) * 3600))
        estimated = fare_estimate_km_based(distance_km=distance_km, duration_sec=duration_sec, surge_multiplier=surge)

        ride = Ride(
            tenant_id=request.tenant_id,
            region=request.region,
            rider_id=request.rider_id,
            pickup_lat=request.pickup_lat,
            pickup_lng=request.pickup_lng,
            destination_lat=request.destination_lat,
            destination_lng=request.destination_lng,
            tier=request.tier,
            payment_method=request.payment_method,
            status="requested",
            surge_multiplier=surge,
            fare_estimate=estimated,
        )
        db.add(ride)
        db.commit()
        db.refresh(ride)

        assignment = assign_driver_to_ride(db, ride)
        if assignment["assigned"]:
            db.refresh(ride)

        response = {
            "id": ride.id,
            "tenant_id": ride.tenant_id,
            "region": ride.region,
            "rider_id": ride.rider_id,
            "status": ride.status,
            "assigned_driver_id": ride.assigned_driver_id,
            "surge_multiplier": ride.surge_multiplier,
            "fare_estimate": ride.fare_estimate,
            "assignment": assignment,
            "trip_id": assignment.get("trip_id"),
        }
        return 201, response

    status, body = run_idempotent(db, request.tenant_id, "POST:/rides", idempotency_key, _action)
    await event_bus.publish(request.tenant_id, "ride.created", body)
    return body


@router.get("/{ride_id}")
def get_ride(ride_id: str, tenant_id: str, db: Session = Depends(get_db)):
    cache_key = f"ride:{tenant_id}:{ride_id}"

    def _producer():
        ride = db.query(Ride).filter(Ride.id == ride_id, Ride.tenant_id == tenant_id).first()
        if not ride:
            raise HTTPException(status_code=404, detail="Ride not found")
        if is_ride_request_timed_out(ride):
            ride.status = "expired"
            db.commit()
            db.refresh(ride)
        return {
            "id": ride.id,
            "tenant_id": ride.tenant_id,
            "region": ride.region,
            "rider_id": ride.rider_id,
            "status": ride.status,
            "assigned_driver_id": ride.assigned_driver_id,
            "surge_multiplier": ride.surge_multiplier,
            "fare_estimate": ride.fare_estimate,
            "final_fare": ride.final_fare,
            "created_at": ride.created_at.isoformat(),
            "updated_at": ride.updated_at.isoformat(),
            "status_reason": "No driver available within 5 minutes" if ride.status == "expired" else None,
        }

    return cached_json(cache_key, ttl_sec=3, producer=_producer)
