import datetime as dt
import uuid

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.db import Base


class Driver(Base):
    __tablename__ = "drivers"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    region: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    vehicle_tier: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="available", index=True)
    lat: Mapped[float | None] = mapped_column(Float, nullable=True)
    lng: Mapped[float | None] = mapped_column(Float, nullable=True)
    is_online: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    last_seen_at: Mapped[dt.datetime] = mapped_column(DateTime, default=dt.datetime.utcnow, index=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=dt.datetime.utcnow)
    updated_at: Mapped[dt.datetime] = mapped_column(DateTime, default=dt.datetime.utcnow, onupdate=dt.datetime.utcnow)


class Ride(Base):
    __tablename__ = "rides"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: str(uuid.uuid4()))
    tenant_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    region: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    rider_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)

    pickup_lat: Mapped[float] = mapped_column(Float, nullable=False)
    pickup_lng: Mapped[float] = mapped_column(Float, nullable=False)
    destination_lat: Mapped[float] = mapped_column(Float, nullable=False)
    destination_lng: Mapped[float] = mapped_column(Float, nullable=False)

    tier: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    payment_method: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="requested", index=True)

    assigned_driver_id: Mapped[str | None] = mapped_column(ForeignKey("drivers.id"), nullable=True, index=True)
    surge_multiplier: Mapped[float] = mapped_column(Float, nullable=False, default=1.0)
    fare_estimate: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    final_fare: Mapped[float | None] = mapped_column(Float, nullable=True)

    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=dt.datetime.utcnow, index=True)
    updated_at: Mapped[dt.datetime] = mapped_column(DateTime, default=dt.datetime.utcnow, onupdate=dt.datetime.utcnow)

    trip: Mapped["Trip"] = relationship("Trip", back_populates="ride", uselist=False)


class Trip(Base):
    __tablename__ = "trips"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: str(uuid.uuid4()))
    tenant_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    region: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    ride_id: Mapped[str] = mapped_column(ForeignKey("rides.id"), nullable=False, unique=True, index=True)
    driver_id: Mapped[str] = mapped_column(ForeignKey("drivers.id"), nullable=False, index=True)
    rider_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)

    status: Mapped[str] = mapped_column(String(32), nullable=False, default="created", index=True)
    started_at: Mapped[dt.datetime | None] = mapped_column(DateTime, nullable=True)
    ended_at: Mapped[dt.datetime | None] = mapped_column(DateTime, nullable=True)

    distance_km: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    duration_sec: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    fare_amount: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)

    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=dt.datetime.utcnow, index=True)
    updated_at: Mapped[dt.datetime] = mapped_column(DateTime, default=dt.datetime.utcnow, onupdate=dt.datetime.utcnow)

    ride: Mapped[Ride] = relationship("Ride", back_populates="trip")


class Payment(Base):
    __tablename__ = "payments"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: str(uuid.uuid4()))
    tenant_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    region: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    ride_id: Mapped[str] = mapped_column(ForeignKey("rides.id"), nullable=False, index=True)
    trip_id: Mapped[str] = mapped_column(ForeignKey("trips.id"), nullable=False, index=True)

    amount: Mapped[float] = mapped_column(Float, nullable=False)
    currency: Mapped[str] = mapped_column(String(8), nullable=False, default="INR")
    payment_method: Mapped[str] = mapped_column(String(32), nullable=False)

    status: Mapped[str] = mapped_column(String(32), nullable=False, default="initiated", index=True)
    psp_reference: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)

    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=dt.datetime.utcnow, index=True)
    updated_at: Mapped[dt.datetime] = mapped_column(DateTime, default=dt.datetime.utcnow, onupdate=dt.datetime.utcnow)


class IdempotencyRecord(Base):
    __tablename__ = "idempotency_records"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tenant_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    endpoint: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    response_status_code: Mapped[int] = mapped_column(Integer, nullable=False)
    response_body: Mapped[dict] = mapped_column(JSON, nullable=False)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=dt.datetime.utcnow, index=True)


class EventLog(Base):
    __tablename__ = "event_logs"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: str(uuid.uuid4()))
    tenant_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    region: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    payload: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=dt.datetime.utcnow, index=True)


Index("uq_idempotency", IdempotencyRecord.tenant_id, IdempotencyRecord.endpoint, IdempotencyRecord.idempotency_key, unique=True)
Index("idx_driver_tenant_region_status_tier", Driver.tenant_id, Driver.region, Driver.status, Driver.vehicle_tier)
Index("idx_ride_tenant_region_status_tier", Ride.tenant_id, Ride.region, Ride.status, Ride.tier)
