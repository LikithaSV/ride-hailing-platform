import datetime as dt

from sqlalchemy.orm import Session

from backend.config import settings
from backend.models import Ride


def _cutoff_ts() -> dt.datetime:
    return dt.datetime.utcnow() - dt.timedelta(seconds=settings.ride_request_timeout_sec)


def is_ride_request_timed_out(ride: Ride) -> bool:
    if ride.status != "requested":
        return False
    return ride.created_at < _cutoff_ts()


def expire_stale_requested_rides(db: Session, tenant_id: str, region: str, tier: str | None = None) -> int:
    query = db.query(Ride).filter(
        Ride.tenant_id == tenant_id,
        Ride.region == region,
        Ride.status == "requested",
        Ride.created_at < _cutoff_ts(),
    )
    if tier:
        query = query.filter(Ride.tier == tier)

    stale = query.all()
    if not stale:
        return 0

    for ride in stale:
        ride.status = "expired"

    db.commit()
    return len(stale)
