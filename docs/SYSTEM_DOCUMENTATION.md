# Ride Hailing Platform - System Documentation

## 1. Objective

This document describes the architecture, behavior, APIs, data model, operational controls, scaling strategy, monitoring approach, and runbook for the ride-hailing platform.

## 2. Functional Scope

Core capabilities:
- Driver onboarding and presence control (online/offline)
- High-frequency driver location ingestion
- Rider pre-booking fare estimate with surge multiplier
- Driver-rider assignment based on nearest available driver
- Driver decline and automatic reassignment
- Trip lifecycle handling
- Payment processing via PSP integration (Cashfree)
- Real-time event notifications for ride lifecycle changes

## 3. Architecture Overview

### 3.1 Components

- API Layer (FastAPI):
  - `backend/routes/`
- Business Services:
  - Dispatch: `backend/services/dispatch_service.py`
  - Surge: `backend/services/surge_service.py`
  - Trip: `backend/services/trip_service.py`
  - Payment: `backend/services/payment_service.py`
  - Timeout: `backend/services/ride_timeout_service.py`
- Data Layer:
  - SQLAlchemy ORM: `backend/models.py`
  - PostgreSQL schema: `backend/models.sql`
- Cache and Index Layer:
  - Redis client/cache helpers: `backend/redis_client.py`
- Real-time Notifications:
  - In-process event bus: `backend/events.py`
  - SSE stream endpoint: `GET /v1/stream`
- Monitoring:
  - New Relic agent/config: `backend/newrelic.ini`

### 3.2 Request Path (High Level)

1. Driver updates location -> Redis hot path + throttled DB sync
2. Rider requests ride -> surge estimate + assignment
3. Assignment writes are transaction-protected
4. Trip starts/ends -> fare computed and persisted
5. Payment executed via PSP integration
6. Lifecycle events published to SSE stream

## 4. Multi-Tenant and Multi-Region Design

- Every business entity carries `tenant_id` and `region`.
- Matching and lookup queries are scoped by `tenant_id + region + tier`.
- Region-local write protection is enforced by `ensure_region_local(...)`.
- `LOCAL_REGION` config rejects cross-region writes in the request path.

## 5. API Specification

Base prefix: `/v1`

### 5.1 Driver APIs

- `POST /drivers/{id}/register`
- `POST /drivers/{id}/location`
- `POST /drivers/{id}/offline`
- `POST /drivers/{id}/decline`

### 5.2 Ride APIs

- `POST /rides/estimate`
- `POST /rides`
- `GET /rides/{id}`

### 5.3 Trip APIs

- `POST /trips/{id}/start`
- `POST /trips/{id}/end`
- `GET /trips/{id}`

### 5.4 Payment API

- `POST /payments`

### 5.5 Notifications API

- `GET /stream?tenant_id=...` (SSE)

## 6. Lifecycle and State Management

### 6.1 Ride States

- `requested`
- `accepted`
- `trip_started`
- `trip_completed`
- `payment_pending`
- `paid`
- `payment_failed`
- `expired`
- `cancelled`

### 6.2 Trip States

- `created`
- `in_progress`
- `ended`

Transition rules are enforced centrally:
- `backend/utils/state_machine.py`

## 7. Timeout and Expiry

- Requested rides are automatically expired after `RIDE_REQUEST_TIMEOUT_SEC` (default 300 seconds).
- Expiry logic runs in:
  - Surge calculation path
  - Ride creation path
  - Ride read path

User-facing reason for expiry:
- `No driver available within 5 minutes`

## 8. Assignment Strategy

Assignment uses nearest available driver with consistency protection:

1. Candidate discovery from Redis GEO index
2. Candidate metadata validation via Redis hash
3. DB row lock (`FOR UPDATE`) on selected driver and ride
4. Atomic state transition to assigned/accepted

Fallback behavior:
- If Redis is unavailable, DB-based candidate lookup is used.

## 9. Scalability Design

### 9.1 High-Frequency Location Ingest

- Redis-first writes for location and metadata
- DB write-behind throttling by `LOCATION_DB_SYNC_INTERVAL_SEC`
- Avoids per-update DB commit under high write rates

### 9.2 Fast Driver Lookup

- Redis GEO index by `{tenant, region, tier}`
- Candidate set bounded by `DISPATCH_CANDIDATE_POOL_SIZE`

### 9.3 Stateless Horizontal Scale

- APIs are stateless
- Shared state externalized to PostgreSQL/Redis
- Safe to run multiple API replicas behind load balancer

### 9.4 Region-Local Write Isolation

- Cross-region synchronous writes are blocked
- Reduces inter-region latency coupling in write path

## 10. Data Model

Primary tables:
- `drivers`
- `rides`
- `trips`
- `payments`
- `idempotency_records`
- `event_logs`

Reference files:
- ORM: `backend/models.py`
- SQL: `backend/models.sql`

## 11. Caching and Indexing

Redis keys used:
- Driver GEO index: `drivers_geo:{tenant}:{region}:{tier}`
- Driver metadata: `driver_meta:{driver_id}`
- Driver location cache: `driver_loc:{driver_id}`
- Ride read cache: `ride:{tenant}:{ride_id}`

Fallback cache:
- Local TTL cache in `backend/redis_client.py` when Redis is disabled.

## 12. Idempotency and Data Consistency

- Mutating endpoints enforce `Idempotency-Key`.
- Response replay for duplicate keys is persisted in `idempotency_records`.
- Assignment/decline/trip/payment sensitive updates run in transaction with row locking.

## 13. Payment Integration

Provider options:
- `cashfree` (external PSP)
- `simulated` (fallback/testing mode)

Cashfree integration points:
- Service: `backend/services/payment_service.py`
- Config keys:
  - `CASHFREE_ENABLED`
  - `CASHFREE_APP_ID`
  - `CASHFREE_SECRET_KEY`
  - `CASHFREE_BASE_URL`
  - `CASHFREE_API_VERSION`
  - `CASHFREE_RETURN_URL`

## 14. Notification Model

Lifecycle events published to SSE stream:
- `driver.registered`
- `driver.location.updated`
- `driver.status.updated`
- `ride.created`
- `ride.assigned`
- `ride.assignment_failed`
- `ride.declined`
- `ride.expired`
- `trip.started`
- `trip.ended`
- `ride.completed`
- `payment.updated`
- `payment.success`
- `payment.failed`
- `stream.heartbeat`

## 15. Monitoring and Performance

New Relic setup and reporting:
- Setup config: `backend/newrelic.ini`
- Detailed performance report template:
  - `docs/PERFORMANCE_REPORT_NEW_RELIC.md`

Track at minimum:
- Endpoint p95 latency
- Error rate
- DB query duration
- External PSP call latency

## 16. Security Baseline

Included:
- Request schema validation
- Tenant/region scoping checks
- Idempotency protection on write endpoints

Recommended hardening:
- JWT authentication
- Role-based authorization
- API rate limiting
- WAF / edge protections
- Service-to-service mTLS

## 17. Configuration Reference

Key runtime parameters:
- `DATABASE_URL`
- `REDIS_ENABLED`
- `REDIS_URL`
- `LOCAL_REGION`
- `DISPATCH_CANDIDATE_POOL_SIZE`
- `LOCATION_DB_SYNC_INTERVAL_SEC`
- `DRIVER_META_TTL_SEC`
- `RIDE_REQUEST_TIMEOUT_SEC`
- `PAYMENT_PROVIDER`
- `CASHFREE_*`
- `NEW_RELIC_ENABLED`

Defaults are defined in `backend/config.py` and examples in `.env.example`.

## 18. Local Runbook

1. Install dependencies
2. Configure `.env`
3. Start backend:

```bash
uvicorn backend.app:app --reload --host 0.0.0.0 --port 8000
```

4. Open frontend and run rider-driver flow.
5. Use SSE stream to verify lifecycle notifications.

## 19. Testing Strategy

Automated tests:
- API flow tests: `backend/tests/test_api.py`
- Coverage includes:
  - End-to-end assignment/trip/payment
  - Idempotency behavior
  - Decline and reassignment
  - Driver online/offline flow
  - Ride timeout expiration

## 20. Known Limitations and Next Steps

- Current SSE event bus is in-process; for multi-replica fan-out, move to Redis Pub/Sub or Kafka.
- For sustained high-scale production traffic, validate with distributed load testing and capacity planning.
- Add asynchronous worker layer for decoupled dispatch if stricter latency isolation is required.
