from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class DriverRegisterRequest(BaseModel):
    tenant_id: str = Field(min_length=1, max_length=64)
    region: str = Field(min_length=1, max_length=64)
    vehicle_tier: Literal["mini", "sedan", "suv", "premium"]


class DriverLocationRequest(BaseModel):
    tenant_id: str = Field(min_length=1, max_length=64)
    region: str = Field(min_length=1, max_length=64)
    lat: float = Field(ge=-90, le=90)
    lng: float = Field(ge=-180, le=180)


class DriverStatusRequest(BaseModel):
    tenant_id: str = Field(min_length=1, max_length=64)
    region: str = Field(min_length=1, max_length=64)


class RideCreateRequest(BaseModel):
    tenant_id: str = Field(min_length=1, max_length=64)
    region: str = Field(min_length=1, max_length=64)
    rider_id: str = Field(min_length=1, max_length=64)
    pickup_lat: float = Field(ge=-90, le=90)
    pickup_lng: float = Field(ge=-180, le=180)
    destination_lat: float = Field(ge=-90, le=90)
    destination_lng: float = Field(ge=-180, le=180)
    tier: Literal["mini", "sedan", "suv", "premium"]
    payment_method: Literal["card", "upi", "cash", "wallet"]


class RideEstimateRequest(BaseModel):
    tenant_id: str = Field(min_length=1, max_length=64)
    region: str = Field(min_length=1, max_length=64)
    pickup_lat: float = Field(ge=-90, le=90)
    pickup_lng: float = Field(ge=-180, le=180)
    destination_lat: float = Field(ge=-90, le=90)
    destination_lng: float = Field(ge=-180, le=180)
    tier: Literal["mini", "sedan", "suv", "premium"]


class DriverDeclineRequest(BaseModel):
    tenant_id: str = Field(min_length=1, max_length=64)
    region: str = Field(min_length=1, max_length=64)
    ride_id: str = Field(min_length=1, max_length=64)


class TripActionRequest(BaseModel):
    tenant_id: str = Field(min_length=1, max_length=64)
    region: str = Field(min_length=1, max_length=64)


class TripEndRequest(BaseModel):
    tenant_id: str = Field(min_length=1, max_length=64)
    region: str = Field(min_length=1, max_length=64)


class PaymentRequest(BaseModel):
    tenant_id: str = Field(min_length=1, max_length=64)
    region: str = Field(min_length=1, max_length=64)
    ride_id: str = Field(min_length=1, max_length=64)


class RideResponse(BaseModel):
    id: str
    tenant_id: str
    region: str
    rider_id: str
    tier: str
    status: str
    assigned_driver_id: str | None
    surge_multiplier: float
    fare_estimate: float
    final_fare: float | None
    created_at: datetime
    updated_at: datetime


class DriverResponse(BaseModel):
    id: str
    tenant_id: str
    region: str
    vehicle_tier: str
    status: str
    lat: float | None
    lng: float | None
    last_seen_at: datetime


class TripResponse(BaseModel):
    id: str
    ride_id: str
    driver_id: str
    status: str
    distance_km: float
    duration_sec: int
    fare_amount: float
    started_at: datetime | None
    ended_at: datetime | None


class PaymentResponse(BaseModel):
    id: str
    ride_id: str
    amount: float
    status: str
    psp_reference: str | None
