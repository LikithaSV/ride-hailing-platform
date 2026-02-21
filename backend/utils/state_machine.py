from fastapi import HTTPException


RIDE_TRANSITIONS = {
    "requested": {"accepted", "expired", "cancelled"},
    "accepted": {"requested", "trip_started", "cancelled"},
    "trip_started": {"trip_completed"},
    "trip_completed": {"payment_pending", "paid", "payment_failed"},
    "payment_pending": {"paid", "payment_failed"},
    "paid": set(),
    "payment_failed": {"payment_pending"},
    "expired": set(),
    "cancelled": set(),
}

TRIP_TRANSITIONS = {
    "created": {"in_progress"},
    "in_progress": {"ended"},
    "ended": set(),
}


def transition(current: str, target: str, machine: dict[str, set[str]], entity: str):
    allowed = machine.get(current, set())
    if target not in allowed:
        raise HTTPException(status_code=409, detail=f"Invalid {entity} transition: {current} -> {target}")
