# Performance Report - New Relic

## 1. Scope

This report documents API performance monitoring for the ride-hailing platform using New Relic.

Target scale:
- ~100k drivers
- ~10k ride requests/min
- high-rate driver location updates

Primary goals:
- Track p50/p95/p99 API latency
- Detect slow DB queries
- Identify bottlenecks under load
- Configure actionable alerts

## 2. Environment

- Service: `backend.app:app` (FastAPI)
- APM config: `backend/newrelic.ini`
- Region mode: `LOCAL_REGION` enabled for region-local writes
- Data stores:
  - Postgres for transactional data
  - Redis for driver geo index + hot cache

## 3. New Relic Setup

1. Configure `backend/newrelic.ini`:
- `license_key` = your New Relic key
- `app_name` = environment-specific name (example: `ride-hailing-platform-prod-in-blr`)

2. Enable monitoring:

```bash
export NEW_RELIC_ENABLED=true
```

3. Start backend:

```bash
uvicorn backend.app:app --host 0.0.0.0 --port 8000
```

4. Verify APM service appears in New Relic dashboard.

## 4. Test Scenarios

Run each scenario for 10-15 minutes and capture screenshots.

### Scenario A - Rider Flow Mix
- `POST /v1/rides/estimate`
- `POST /v1/rides`
- `GET /v1/rides/{id}`
- `POST /v1/trips/{id}/start`
- `POST /v1/trips/{id}/end`
- `POST /v1/payments`

### Scenario B - Driver Presence + Location
- `POST /v1/drivers/{id}/register`
- `POST /v1/drivers/{id}/location` (high-frequency)
- `POST /v1/drivers/{id}/offline`

### Scenario C - Assignment Contention
- High concurrent `POST /v1/rides` with limited available drivers
- Measure assignment latency and error rates

## 5. Dashboard Checklist

Capture these charts in New Relic APM:
- Throughput (requests/min)
- Average response time
- p95/p99 response time by endpoint
- Error rate by endpoint
- Datastore operations by table
- Slow SQL traces
- External calls latency (Cashfree)

## 6. Core NRQL Queries

### 6.1 Endpoint Latency (p95)

```sql
SELECT percentile(duration, 95)
FROM Transaction
WHERE appName = 'ride-hailing-platform'
FACET name
SINCE 30 minutes AGO
```

### 6.2 Error Rate by Endpoint

```sql
SELECT percentage(count(*), WHERE error IS true) AS 'error_rate_pct'
FROM Transaction
WHERE appName = 'ride-hailing-platform'
FACET name
SINCE 30 minutes AGO
```

### 6.3 Throughput

```sql
SELECT rate(count(*), 1 minute)
FROM Transaction
WHERE appName = 'ride-hailing-platform'
TIMESERIES
SINCE 30 minutes AGO
```

### 6.4 Slow DB Statements

```sql
SELECT average(databaseDuration), percentile(databaseDuration, 95)
FROM Transaction
WHERE appName = 'ride-hailing-platform'
FACET name
SINCE 30 minutes AGO
```

### 6.5 External PSP Calls

```sql
SELECT average(duration), percentile(duration, 95)
FROM Span
WHERE appName = 'ride-hailing-platform'
AND category = 'http'
FACET http.url
SINCE 30 minutes AGO
```

## 7. Alert Policies

Recommended alert thresholds:
- API p95 latency > 1000 ms for 5 minutes
- Error rate > 2% for 5 minutes
- DB duration p95 > 300 ms for 5 minutes
- External PSP call p95 > 1500 ms for 5 minutes

## 8. Performance Findings (Report Template)

Fill this table after load run:

| Metric | Target | Observed | Status |
|---|---:|---:|---|
| `POST /v1/rides` p95 | <= 1000 ms | _fill_ | _pass/fail_ |
| `GET /v1/rides/{id}` p95 | <= 300 ms | _fill_ | _pass/fail_ |
| `POST /v1/drivers/{id}/location` p95 | <= 200 ms | _fill_ | _pass/fail_ |
| Error rate overall | < 2% | _fill_ | _pass/fail_ |
| Slow query p95 | <= 300 ms | _fill_ | _pass/fail_ |
| PSP call p95 | <= 1500 ms | _fill_ | _pass/fail_ |

## 9. Bottlenecks to Watch

- Redis latency spikes can impact driver lookup and surge availability counts.
- Postgres contention during assignment (`FOR UPDATE`) can raise p95 under burst traffic.
- External PSP latency affects payment completion time.
- Local in-memory SSE bus does not fan out across multiple replicas.

## 10. Optimization Actions

- Keep Redis in-memory hot set for location + dispatch indexes.
- Increase `DISPATCH_CANDIDATE_POOL_SIZE` carefully to balance match quality vs lookup cost.
- Tune `LOCATION_DB_SYNC_INTERVAL_SEC` to reduce DB write pressure.
- Add DB index review for hot write/read paths (`rides`, `drivers`, `trips`).
- Move SSE to Redis Pub/Sub or Kafka for multi-replica deployments.

## 11. Evidence to Submit

- New Relic dashboard screenshots:
  - Throughput
  - p95/p99 latency
  - Error rate
  - DB slow queries
  - External PSP call latency
- This report with filled metrics table
- Any action items + before/after comparison
