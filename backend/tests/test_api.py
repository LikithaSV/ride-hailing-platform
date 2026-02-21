import os

from fastapi.testclient import TestClient

os.environ["DATABASE_URL"] = "sqlite:///./test_ride_hailing.db"
os.environ["REDIS_ENABLED"] = "false"

from backend.app import app  # noqa: E402


def headers(key: str):
    return {"Idempotency-Key": key}


def test_prebooking_estimate_returns_surge_and_fares():
    with TestClient(app) as client:
        tenant = "tenant-estimate"
        region = "in-blr"

        estimate = client.post(
            "/v1/rides/estimate",
            json={
                "tenant_id": tenant,
                "region": region,
                "pickup_lat": 12.9755,
                "pickup_lng": 77.6060,
                "destination_lat": 12.9352,
                "destination_lng": 77.6245,
                "tier": "mini",
            },
        )
        assert estimate.status_code == 200
        payload = estimate.json()
        assert payload["distance_km"] > 0
        assert payload["surge_multiplier"] >= 1.0
        assert payload["estimated_fare"] >= payload["fare_without_surge"]


def test_end_to_end_flow_with_auto_assignment():
    with TestClient(app) as client:
        tenant = "tenant-test"
        region = "in-blr"

        res = client.post(
            "/v1/drivers/driver-t1/register",
            headers=headers("d-register-1"),
            json={"tenant_id": tenant, "region": region, "vehicle_tier": "mini"},
        )
        assert res.status_code == 200

        res = client.post(
            "/v1/drivers/driver-t1/location",
            json={"tenant_id": tenant, "region": region, "lat": 12.9716, "lng": 77.5946},
        )
        assert res.status_code == 200

        ride_res = client.post(
            "/v1/rides",
            headers=headers("ride-1"),
            json={
                "tenant_id": tenant,
                "region": region,
                "rider_id": "r1",
                "pickup_lat": 12.9717,
                "pickup_lng": 77.5947,
                "destination_lat": 12.93,
                "destination_lng": 77.62,
                "tier": "mini",
                "payment_method": "upi",
            },
        )
        assert ride_res.status_code in (200, 201)
        ride_payload = ride_res.json()
        ride_id = ride_payload["id"]
        assert ride_payload["assignment"]["assigned"] is True

        trip_id = ride_payload["trip_id"]
        assert trip_id

        get_res = client.get(f"/v1/rides/{ride_id}", params={"tenant_id": tenant})
        assert get_res.status_code == 200
        assert get_res.json()["status"] == "accepted"

        start_res = client.post(
            f"/v1/trips/{trip_id}/start",
            headers=headers("start-1"),
            json={"tenant_id": tenant, "region": region},
        )
        assert start_res.status_code == 200

        end_res = client.post(
            f"/v1/trips/{trip_id}/end",
            headers=headers("end-1"),
            json={"tenant_id": tenant, "region": region},
        )
        assert end_res.status_code == 200
        assert end_res.json()["distance_km"] > 0
        assert end_res.json()["duration_sec"] > 0

        pay_res = client.post(
            "/v1/payments",
            headers=headers("payment-1"),
            json={"tenant_id": tenant, "region": region, "ride_id": ride_id},
        )
        assert pay_res.status_code == 200
        assert pay_res.json()["status"] in {"success", "failed"}


def test_driver_can_decline_and_reassignment_happens():
    with TestClient(app) as client:
        tenant = "tenant-decline"
        region = "in-blr"

        for driver_id, lat, lng in [
            ("driver-d1", 12.9717, 77.5948),
            ("driver-d2", 12.9725, 77.5960),
        ]:
            client.post(
                f"/v1/drivers/{driver_id}/register",
                headers=headers(f"register-{driver_id}"),
                json={"tenant_id": tenant, "region": region, "vehicle_tier": "mini"},
            )
            client.post(
                f"/v1/drivers/{driver_id}/location",
                json={"tenant_id": tenant, "region": region, "lat": lat, "lng": lng},
            )

        create = client.post(
            "/v1/rides",
            headers=headers("ride-decline-1"),
            json={
                "tenant_id": tenant,
                "region": region,
                "rider_id": "r1",
                "pickup_lat": 12.9716,
                "pickup_lng": 77.5947,
                "destination_lat": 12.93,
                "destination_lng": 77.62,
                "tier": "mini",
                "payment_method": "card",
            },
        )
        assert create.status_code in (200, 201)
        payload = create.json()
        first_driver = payload["assigned_driver_id"]
        assert first_driver in {"driver-d1", "driver-d2"}

        decline = client.post(
            f"/v1/drivers/{first_driver}/decline",
            headers=headers("decline-1"),
            json={"tenant_id": tenant, "region": region, "ride_id": payload["id"]},
        )
        assert decline.status_code == 200
        reassignment = decline.json()["reassignment"]
        assert reassignment["assigned"] is True
        assert reassignment["driver_id"] != first_driver


def test_idempotent_ride_create():
    with TestClient(app) as client:
        tenant = "tenant-idempotent"
        region = "in-blr"

        client.post(
            "/v1/drivers/driver-i1/register",
            headers=headers("d-register-i1"),
            json={"tenant_id": tenant, "region": region, "vehicle_tier": "mini"},
        )
        client.post(
            "/v1/drivers/driver-i1/location",
            json={"tenant_id": tenant, "region": region, "lat": 12.9716, "lng": 77.5946},
        )

        payload = {
            "tenant_id": tenant,
            "region": region,
            "rider_id": "r1",
            "pickup_lat": 12.9717,
            "pickup_lng": 77.5947,
            "destination_lat": 12.93,
            "destination_lng": 77.62,
            "tier": "mini",
            "payment_method": "card",
        }

        r1 = client.post("/v1/rides", headers=headers("idem-ride-1"), json=payload)
        r2 = client.post("/v1/rides", headers=headers("idem-ride-1"), json=payload)

        assert r1.status_code in (200, 201)
        assert r2.status_code in (200, 201)
        assert r1.json()["id"] == r2.json()["id"]


def test_driver_online_offline_buttons_flow():
    with TestClient(app) as client:
        tenant = "tenant-presence"
        region = "in-blr"
        driver_id = "driver-presence-1"

        reg = client.post(
            f"/v1/drivers/{driver_id}/register",
            headers=headers("presence-register"),
            json={"tenant_id": tenant, "region": region, "vehicle_tier": "mini"},
        )
        assert reg.status_code == 200

        online = client.post(
            f"/v1/drivers/{driver_id}/location",
            json={"tenant_id": tenant, "region": region, "lat": 12.9755, "lng": 77.6060},
        )
        assert online.status_code == 200
        assert online.json()["status"] in {"available", "on_trip"}

        offline = client.post(
            f"/v1/drivers/{driver_id}/offline",
            headers=headers("presence-offline"),
            json={"tenant_id": tenant, "region": region},
        )
        assert offline.status_code == 200
        assert offline.json()["status"] == "offline"
