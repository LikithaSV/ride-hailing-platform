# GoComet DAW Ride Hailing Platform

Multi-tenant, multi-region ride hailing backend + live frontend built with FastAPI, SQLAlchemy, Redis-compatible caching, and SSE live updates.

## What is implemented

- Core APIs
  - `POST /v1/rides/estimate` (pre-booking surge fare preview)
  - `POST /v1/rides`
  - `GET /v1/rides/{id}`
  - `POST /v1/drivers/{id}/location`
  - `POST /v1/drivers/{id}/offline`
  - `POST /v1/drivers/{id}/decline`
  - `POST /v1/trips/{id}/end`
  - `POST /v1/payments`
- Extra APIs for complete lifecycle
  - `POST /v1/drivers/{id}/register`
  - `POST /v1/trips/{id}/start`
  - `GET /v1/trips/{id}`
  - `GET /v1/stream?tenant_id=...` (SSE live events)
- Validation using Pydantic request schemas
- Idempotency for all mutating APIs via `Idempotency-Key` header
- Clean state transitions for ride and trip state machines
- Transactional assignment and reassignment (`SELECT ... FOR UPDATE` style locking)
- Dynamic surge pricing based on demand/supply
  - Surge moves in practical fixed steps: `1.0x -> 1.2x -> 1.4x -> 1.6x ...`
- Driver matching with Redis GEO index (if enabled) and DB fallback
- High-throughput location ingest path: Redis-first writes + throttled write-behind sync to DB
- Caching on `GET /v1/rides/{id}` using Redis or local TTL cache
- Payment flow via external PSP (Cashfree) with simulation fallback and retry-friendly state
- Pytest tests for end-to-end and idempotency behavior
- New Relic config included (`backend/newrelic.ini`)

## HLD (high-level)

- API layer: FastAPI stateless service
- Service layer: `dispatch_service`, `trip_service`, `surge_service`, `payment_service`
- Data layer: SQL transactional tables for drivers/rides/trips/payments/idempotency
- Cache/index layer: Redis GEO (optional) + TTL read cache
- Live updates: in-process event bus + SSE stream endpoint
- Multi-tenant/multi-region isolation: all major records include `tenant_id` and `region`; matching and queries scoped by both

## LLD (key consistency and latency choices)

- Driver allocation consistency
  - Lock driver + ride rows during assignment/decline-reassignment to avoid double allocation race
  - Transition checks prevent invalid lifecycle jumps
- API latency optimization
  - Composite DB indexes for assignment, status, and tenant/region access patterns
  - Cached ride status reads (`GET /v1/rides/{id}`)
  - Redis GEO lookup for fast nearby-driver candidate fetch
- Reliability
  - Idempotency table for safe retries across network/client duplicates
  - Payment workflow supports `payment_failed -> payment_pending -> paid`
  - Driver assignment is automatic to nearest available; driver action is decline-only, triggering reassignment
  - Trip end uses route coordinates + runtime to compute distance/duration automatically (no manual meter input)
  - Requested rides auto-expire after timeout (`RIDE_REQUEST_TIMEOUT_SEC`, default 300s)
  - Region-local write guard available via `LOCAL_REGION` to avoid cross-region write coupling

## Scale Notes

- Designed for high-load patterns:
  - ~100k drivers
  - ~10k ride requests/min
  - up to very high location update throughput using Redis hot-path
- Location updates:
  - API writes location directly to Redis GEO + metadata cache
  - DB sync is throttled (`LOCATION_DB_SYNC_INTERVAL_SEC`) to reduce write amplification
- Matching:
  - Candidate lookup is cache-first from Redis GEO
  - Final allocation consistency still enforced by DB row locks
- Horizontal stateless APIs:
  - API instances keep no in-process state
  - Safe to scale replicas behind load balancer
- Region-local writes:
  - Set `LOCAL_REGION` in each regional deployment
  - Cross-region write requests are rejected early

## Project structure

- `backend/app.py` FastAPI app + SSE endpoint
- `backend/routes/*` APIs
- `backend/services/*` business logic
- `backend/models.py` ORM entities + indexes
- `backend/models.sql` PostgreSQL schema
- `backend/tests/test_api.py` tests
- `frontend/index.html` split-screen Rider Console + Driver Console
- `frontend/script.js` live API, predefined locations, pre-booking fare details

## Run locally

1. Create and activate virtual env.

```bash
python3 -m venv .venv
source .venv/bin/activate
```

2. Install dependencies.

```bash
pip install -r requirements.txt
```

3. Start backend.

```bash
uvicorn backend.app:app --reload --host 0.0.0.0 --port 8000
```

4. Open frontend.

- Open `frontend/index.html` in browser.
- Use the controls in this sequence:
  1. Register driver
  2. Driver goes online at a preset location
  3. Connect live stream
  4. Rider checks price before booking (`/v1/rides/estimate`)
  5. Rider books ride
  6. Driver decline (optional; system reassigns nearest available)
  7. Start trip
  8. End trip
  9. Trigger payment

## Environment variables

- `DATABASE_URL` (recommended: `postgresql+psycopg2://postgres:postgres@localhost:5432/ride_hailing`)
- `REDIS_ENABLED` (`true`/`false`, default `false`)
- `REDIS_URL` (default `redis://localhost:6379/0`)
- `CORS_ORIGINS` (default `*`)
- `NEW_RELIC_ENABLED` (`true`/`false`)
- `LOCAL_REGION` (optional; enforce in-region writes)
- `DISPATCH_CANDIDATE_POOL_SIZE` (default `64`)
- `LOCATION_DB_SYNC_INTERVAL_SEC` (default `15`)
- `DRIVER_META_TTL_SEC` (default `120`)
- `RIDE_REQUEST_TIMEOUT_SEC` (default `300`)
- `PAYMENT_PROVIDER` (`cashfree` or `simulated`)
- `CASHFREE_ENABLED` (`true`/`false`)
- `CASHFREE_BASE_URL` (default sandbox URL)
- `CASHFREE_API_VERSION` (default `2023-08-01`)
- `CASHFREE_APP_ID`
- `CASHFREE_SECRET_KEY`
- `CASHFREE_RETURN_URL`

Example local Postgres DB:

```bash
export DATABASE_URL='postgresql+psycopg2://postgres:postgres@localhost:5432/ride_hailing'
```

Example production DB:

```bash
export DATABASE_URL='postgresql+psycopg2://user:pass@localhost:5432/ride_hailing'
```

Cashfree sandbox example:

```bash
export PAYMENT_PROVIDER='cashfree'
export CASHFREE_ENABLED=true
export CASHFREE_BASE_URL='https://sandbox.cashfree.com/pg'
export CASHFREE_APP_ID='<your_app_id>'
export CASHFREE_SECRET_KEY='<your_secret_key>'
```

## Run tests

```bash
pytest -q
```

## New Relic setup

1. Put your license key into `backend/newrelic.ini`.
2. Enable monitoring:

```bash
export NEW_RELIC_ENABLED=true
```

3. Start API and observe:
- Throughput
- p95 latency
- Transaction traces
- Slow SQL traces

## Security baseline included

- Strict request validation
- Tenant/region scoping checks
- Idempotency enforcement for mutable endpoints

For production hardening add authentication/JWT, rate limits, WAF, and mTLS between services.
