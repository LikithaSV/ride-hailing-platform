import math

from sqlalchemy import func
from sqlalchemy.orm import Session

from backend.config import settings
from backend.models import Driver, Ride


def get_surge_multiplier(db: Session, tenant_id: str, region: str, tier: str) -> float:
    active_requests = (
        db.query(func.count(Ride.id))
        .filter(Ride.tenant_id == tenant_id, Ride.region == region, Ride.tier == tier, Ride.status.in_(["requested", "accepted"]))
        .scalar()
        or 0
    )
    available_drivers = (
        db.query(func.count(Driver.id))
        .filter(
            Driver.tenant_id == tenant_id,
            Driver.region == region,
            Driver.vehicle_tier == tier,
            Driver.status == "available",
            Driver.is_online.is_(True),
        )
        .scalar()
        or 0
    )

    if available_drivers <= 0:
        return settings.surge_max

    pressure_ratio = active_requests / max(1, available_drivers)
    step_index = max(0, math.ceil((pressure_ratio - 0.5) / 0.5))
    stepped_multiplier = settings.surge_base + (0.2 * step_index)
    return round(min(settings.surge_max, max(settings.surge_base, stepped_multiplier)), 2)


def fare_estimate_km_based(distance_km: float, duration_sec: int, surge_multiplier: float) -> float:
    base_fare = 40.0
    per_km = 14.0
    per_min = 1.5
    raw = base_fare + (distance_km * per_km) + ((duration_sec / 60.0) * per_min)
    return round(raw * surge_multiplier, 2)
