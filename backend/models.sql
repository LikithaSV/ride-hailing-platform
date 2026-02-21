-- PostgreSQL schema for production use.

CREATE TABLE IF NOT EXISTS drivers (
    id VARCHAR(64) PRIMARY KEY,
    tenant_id VARCHAR(64) NOT NULL,
    region VARCHAR(64) NOT NULL,
    vehicle_tier VARCHAR(32) NOT NULL,
    status VARCHAR(32) NOT NULL,
    lat DOUBLE PRECISION,
    lng DOUBLE PRECISION,
    is_online BOOLEAN NOT NULL DEFAULT TRUE,
    last_seen_at TIMESTAMP NOT NULL DEFAULT NOW(),
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS rides (
    id VARCHAR(64) PRIMARY KEY,
    tenant_id VARCHAR(64) NOT NULL,
    region VARCHAR(64) NOT NULL,
    rider_id VARCHAR(64) NOT NULL,
    pickup_lat DOUBLE PRECISION NOT NULL,
    pickup_lng DOUBLE PRECISION NOT NULL,
    destination_lat DOUBLE PRECISION NOT NULL,
    destination_lng DOUBLE PRECISION NOT NULL,
    tier VARCHAR(32) NOT NULL,
    payment_method VARCHAR(32) NOT NULL,
    status VARCHAR(32) NOT NULL,
    assigned_driver_id VARCHAR(64) REFERENCES drivers(id),
    surge_multiplier DOUBLE PRECISION NOT NULL DEFAULT 1,
    fare_estimate DOUBLE PRECISION NOT NULL DEFAULT 0,
    final_fare DOUBLE PRECISION,
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS trips (
    id VARCHAR(64) PRIMARY KEY,
    tenant_id VARCHAR(64) NOT NULL,
    region VARCHAR(64) NOT NULL,
    ride_id VARCHAR(64) NOT NULL UNIQUE REFERENCES rides(id),
    driver_id VARCHAR(64) NOT NULL REFERENCES drivers(id),
    rider_id VARCHAR(64) NOT NULL,
    status VARCHAR(32) NOT NULL,
    started_at TIMESTAMP,
    ended_at TIMESTAMP,
    distance_km DOUBLE PRECISION NOT NULL DEFAULT 0,
    duration_sec INTEGER NOT NULL DEFAULT 0,
    fare_amount DOUBLE PRECISION NOT NULL DEFAULT 0,
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS payments (
    id VARCHAR(64) PRIMARY KEY,
    tenant_id VARCHAR(64) NOT NULL,
    region VARCHAR(64) NOT NULL,
    ride_id VARCHAR(64) NOT NULL REFERENCES rides(id),
    trip_id VARCHAR(64) NOT NULL REFERENCES trips(id),
    amount DOUBLE PRECISION NOT NULL,
    currency VARCHAR(8) NOT NULL,
    payment_method VARCHAR(32) NOT NULL,
    status VARCHAR(32) NOT NULL,
    psp_reference VARCHAR(128),
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS idempotency_records (
    id BIGSERIAL PRIMARY KEY,
    tenant_id VARCHAR(64) NOT NULL,
    endpoint VARCHAR(128) NOT NULL,
    idempotency_key VARCHAR(128) NOT NULL,
    response_status_code INTEGER NOT NULL,
    response_body JSONB NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    UNIQUE (tenant_id, endpoint, idempotency_key)
);

CREATE TABLE IF NOT EXISTS event_logs (
    id VARCHAR(64) PRIMARY KEY,
    tenant_id VARCHAR(64) NOT NULL,
    region VARCHAR(64) NOT NULL,
    event_type VARCHAR(64) NOT NULL,
    payload TEXT NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_driver_tenant_region_status_tier ON drivers(tenant_id, region, status, vehicle_tier);
CREATE INDEX IF NOT EXISTS idx_ride_tenant_region_status_tier ON rides(tenant_id, region, status, tier);
CREATE INDEX IF NOT EXISTS idx_trip_tenant_region_status ON trips(tenant_id, region, status);
CREATE INDEX IF NOT EXISTS idx_payment_tenant_region_status ON payments(tenant_id, region, status);
