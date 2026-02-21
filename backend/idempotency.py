from collections.abc import Callable

from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.models import IdempotencyRecord


def require_idempotency_key(idempotency_key: str | None):
    if not idempotency_key:
        raise HTTPException(status_code=400, detail="Missing Idempotency-Key header")


def run_idempotent(
    db: Session,
    tenant_id: str,
    endpoint: str,
    idempotency_key: str,
    action: Callable[[], tuple[int, dict]],
):
    existing = (
        db.query(IdempotencyRecord)
        .filter(
            IdempotencyRecord.tenant_id == tenant_id,
            IdempotencyRecord.endpoint == endpoint,
            IdempotencyRecord.idempotency_key == idempotency_key,
        )
        .first()
    )
    if existing:
        return existing.response_status_code, existing.response_body

    status_code, body = action()
    record = IdempotencyRecord(
        tenant_id=tenant_id,
        endpoint=endpoint,
        idempotency_key=idempotency_key,
        response_status_code=status_code,
        response_body=body,
    )
    db.add(record)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        existing = (
            db.query(IdempotencyRecord)
            .filter(
                IdempotencyRecord.tenant_id == tenant_id,
                IdempotencyRecord.endpoint == endpoint,
                IdempotencyRecord.idempotency_key == idempotency_key,
            )
            .first()
        )
        if not existing:
            raise
        return existing.response_status_code, existing.response_body

    return status_code, body
