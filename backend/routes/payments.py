from fastapi import APIRouter, Depends, Header
from sqlalchemy.orm import Session

from backend.db import get_db
from backend.events import event_bus
from backend.idempotency import require_idempotency_key, run_idempotent
from backend.schemas import PaymentRequest
from backend.services.payment_service import trigger_payment
from backend.utils.region_guard import ensure_region_local

router = APIRouter(prefix="/payments", tags=["payments"])


@router.post("")
async def create_payment(
    request: PaymentRequest,
    db: Session = Depends(get_db),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    require_idempotency_key(idempotency_key)
    ensure_region_local(request.region)

    def _action():
        payment = trigger_payment(db, tenant_id=request.tenant_id, region=request.region, ride_id=request.ride_id)
        return 200, {
            "id": payment.id,
            "ride_id": payment.ride_id,
            "amount": payment.amount,
            "status": payment.status,
            "psp_reference": payment.psp_reference,
        }

    status, body = run_idempotent(db, request.tenant_id, "POST:/payments", idempotency_key, _action)
    await event_bus.publish(request.tenant_id, "payment.updated", body)
    return body
