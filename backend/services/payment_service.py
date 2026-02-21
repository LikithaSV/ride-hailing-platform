import random
import uuid

import httpx
from fastapi import HTTPException
from sqlalchemy.orm import Session

from backend.config import settings
from backend.models import Payment, Ride, Trip
from backend.utils.state_machine import RIDE_TRANSITIONS, transition


def _simulate_psp_charge() -> tuple[bool, str]:
    success = random.random() < 0.95
    return success, f"sim_{uuid.uuid4().hex[:16]}"


def _cashfree_charge(payment: Payment, rider_id: str) -> tuple[bool, str]:
    if not settings.cashfree_enabled:
        return _simulate_psp_charge()

    if not settings.cashfree_app_id or not settings.cashfree_secret_key:
        raise HTTPException(status_code=500, detail="Cashfree is enabled but credentials are missing")

    payload = {
        "order_id": payment.id,
        "order_amount": round(payment.amount, 2),
        "order_currency": payment.currency,
        "customer_details": {
            "customer_id": rider_id,
            "customer_email": f"{rider_id}@example.com",
            "customer_phone": "9999999999",
        },
        "order_meta": {
            "return_url": settings.cashfree_return_url,
        },
    }

    headers = {
        "x-client-id": settings.cashfree_app_id,
        "x-client-secret": settings.cashfree_secret_key,
        "x-api-version": settings.cashfree_api_version,
        "content-type": "application/json",
    }

    try:
        with httpx.Client(timeout=10.0) as client:
            response = client.post(f"{settings.cashfree_base_url}/orders", json=payload, headers=headers)
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail=f"Cashfree request failed: {exc}") from exc

    if response.status_code not in (200, 201):
        raise HTTPException(status_code=502, detail=f"Cashfree error: {response.text}")

    body = response.json()
    reference = body.get("cf_order_id") or body.get("order_id") or f"cashfree_{payment.id}"
    return True, reference


def trigger_payment(db: Session, tenant_id: str, region: str, ride_id: str) -> Payment:
    ride = db.query(Ride).filter(Ride.id == ride_id).with_for_update().first()
    if not ride:
        raise HTTPException(status_code=404, detail="Ride not found")
    if ride.tenant_id != tenant_id or ride.region != region:
        raise HTTPException(status_code=400, detail="Tenant/region mismatch")
    if ride.status not in {"trip_completed", "payment_pending", "payment_failed"}:
        raise HTTPException(status_code=409, detail=f"Payment cannot start from ride status {ride.status}")

    trip = db.query(Trip).filter(Trip.ride_id == ride_id).first()
    if not trip:
        raise HTTPException(status_code=404, detail="Trip not found")

    transition(ride.status, "payment_pending", RIDE_TRANSITIONS, "ride")
    ride.status = "payment_pending"

    payment = Payment(
        tenant_id=tenant_id,
        region=region,
        ride_id=ride.id,
        trip_id=trip.id,
        amount=ride.final_fare or trip.fare_amount,
        currency="INR",
        payment_method=ride.payment_method,
        status="initiated",
    )
    db.add(payment)
    db.flush()

    if settings.payment_provider.lower() == "cashfree":
        success, psp_ref = _cashfree_charge(payment, rider_id=ride.rider_id)
    else:
        success, psp_ref = _simulate_psp_charge()

    payment.psp_reference = psp_ref
    if success:
        payment.status = "success"
        transition(ride.status, "paid", RIDE_TRANSITIONS, "ride")
        ride.status = "paid"
    else:
        payment.status = "failed"
        transition(ride.status, "payment_failed", RIDE_TRANSITIONS, "ride")
        ride.status = "payment_failed"

    db.commit()
    db.refresh(payment)
    return payment
