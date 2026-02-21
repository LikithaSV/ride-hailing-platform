from fastapi import APIRouter, Depends, Header
from sqlalchemy.orm import Session

from backend.db import get_db
from backend.events import event_bus
from backend.idempotency import require_idempotency_key, run_idempotent
from backend.schemas import DriverDeclineRequest, DriverLocationRequest, DriverRegisterRequest, DriverStatusRequest
from backend.services.dispatch_service import driver_decline_ride, register_driver, set_driver_offline, upsert_driver_location
from backend.utils.region_guard import ensure_region_local

router = APIRouter(prefix="/drivers", tags=["drivers"])


@router.post("/{driver_id}/register")
async def register_driver_endpoint(
    driver_id: str,
    request: DriverRegisterRequest,
    db: Session = Depends(get_db),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    require_idempotency_key(idempotency_key)
    ensure_region_local(request.region)

    def _action():
        driver = register_driver(
            db,
            driver_id=driver_id,
            tenant_id=request.tenant_id,
            region=request.region,
            vehicle_tier=request.vehicle_tier,
        )
        return 200, {
            "id": driver.id,
            "tenant_id": driver.tenant_id,
            "region": driver.region,
            "vehicle_tier": driver.vehicle_tier,
            "status": driver.status,
        }

    status, body = run_idempotent(db, request.tenant_id, f"POST:/drivers/{driver_id}/register", idempotency_key, _action)
    await event_bus.publish(request.tenant_id, "driver.registered", body)
    return body


@router.post("/{driver_id}/location")
async def update_location(
    driver_id: str,
    request: DriverLocationRequest,
    db: Session = Depends(get_db),
):
    ensure_region_local(request.region)
    payload = upsert_driver_location(
        db,
        driver_id=driver_id,
        tenant_id=request.tenant_id,
        region=request.region,
        lat=request.lat,
        lng=request.lng,
    )
    await event_bus.publish(request.tenant_id, "driver.location.updated", payload)
    return payload


@router.post("/{driver_id}/offline")
async def set_offline(
    driver_id: str,
    request: DriverStatusRequest,
    db: Session = Depends(get_db),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    require_idempotency_key(idempotency_key)
    ensure_region_local(request.region)

    def _action():
        driver = set_driver_offline(db, driver_id=driver_id, tenant_id=request.tenant_id, region=request.region)
        return 200, {
            "id": driver.id,
            "tenant_id": driver.tenant_id,
            "region": driver.region,
            "status": driver.status,
            "is_online": driver.is_online,
        }

    status, body = run_idempotent(db, request.tenant_id, f"POST:/drivers/{driver_id}/offline", idempotency_key, _action)
    await event_bus.publish(request.tenant_id, "driver.status.updated", body)
    return body


@router.post("/{driver_id}/decline")
async def decline_ride(
    driver_id: str,
    request: DriverDeclineRequest,
    db: Session = Depends(get_db),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    require_idempotency_key(idempotency_key)
    ensure_region_local(request.region)

    def _action():
        outcome = driver_decline_ride(
            db,
            tenant_id=request.tenant_id,
            region=request.region,
            driver_id=driver_id,
            ride_id=request.ride_id,
        )
        return 200, outcome

    status, body = run_idempotent(db, request.tenant_id, f"POST:/drivers/{driver_id}/decline", idempotency_key, _action)
    await event_bus.publish(request.tenant_id, "ride.declined", body)
    reassignment = body.get("reassignment", {})
    if reassignment.get("assigned"):
        await event_bus.publish(
            request.tenant_id,
            "ride.assigned",
            {
                "ride_id": body.get("ride_id"),
                "driver_id": reassignment.get("driver_id"),
                "trip_id": reassignment.get("trip_id"),
                "distance_km": reassignment.get("distance_km"),
            },
        )
    else:
        await event_bus.publish(
            request.tenant_id,
            "ride.assignment_failed",
            {"ride_id": body.get("ride_id"), "reason": reassignment.get("reason", "No available driver")},
        )
    return body
