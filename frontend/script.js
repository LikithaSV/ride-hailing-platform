const API = "http://127.0.0.1:8000/v1";
const logEl = document.getElementById("log");
const estimateResultEl = document.getElementById("estimateResult");

const LOCATION_SPOTS = {
  mg_road: { name: "MG Road", lat: 12.9755, lng: 77.6060 },
  indiranagar: { name: "Indiranagar", lat: 12.9719, lng: 77.6412 },
  koramangala: { name: "Koramangala", lat: 12.9352, lng: 77.6245 },
  whitefield: { name: "Whitefield", lat: 12.9698, lng: 77.75 },
  hebbal: { name: "Hebbal", lat: 13.0358, lng: 77.5970 },
};

function log(data) {
  const line = typeof data === "string" ? data : JSON.stringify(data, null, 2);
  logEl.textContent = `[${new Date().toISOString()}] ${line}\n\n` + logEl.textContent;
}

function randomKey(prefix) {
  return `${prefix}-${crypto.randomUUID()}`;
}

async function api(path, method, body, idemPrefix = "req", withIdempotency = true) {
  const headers = { "Content-Type": "application/json" };
  if (withIdempotency) {
    headers["Idempotency-Key"] = randomKey(idemPrefix);
  }

  const res = await fetch(`${API}${path}`, {
    method,
    headers,
    body: body ? JSON.stringify(body) : undefined,
  });
  const data = await res.json();
  if (!res.ok) {
    log({ error: `HTTP ${res.status}`, data });
    throw new Error(`HTTP ${res.status}`);
  }
  log({ method, path, data });
  return data;
}

function commonContext() {
  return {
    tenant_id: document.getElementById("tenant").value,
    region: document.getElementById("region").value,
  };
}

function getSpot(selectId) {
  return LOCATION_SPOTS[document.getElementById(selectId).value];
}

function fillSpotDropdown(selectId, defaultKey) {
  const select = document.getElementById(selectId);
  Object.entries(LOCATION_SPOTS).forEach(([key, spot]) => {
    const option = document.createElement("option");
    option.value = key;
    option.textContent = `${spot.name} (${spot.lat.toFixed(3)}, ${spot.lng.toFixed(3)})`;
    if (key === defaultKey) option.selected = true;
    select.appendChild(option);
  });
}

fillSpotDropdown("driverSpot", "mg_road");
fillSpotDropdown("pickupSpot", "mg_road");
fillSpotDropdown("dropSpot", "koramangala");

document.getElementById("registerDriverBtn").onclick = async () => {
  const driverId = document.getElementById("driverId").value;
  await api(
    `/drivers/${driverId}/register`,
    "POST",
    {
      ...commonContext(),
      vehicle_tier: document.getElementById("tier").value,
    },
    "register"
  );
};

document.getElementById("driverOnlineBtn").onclick = async () => {
  const driverId = document.getElementById("driverId").value;
  const spot = getSpot("driverSpot");
  await api(
    `/drivers/${driverId}/location`,
    "POST",
    {
      ...commonContext(),
      lat: spot.lat,
      lng: spot.lng,
    },
    "loc",
    false
  );
};

document.getElementById("driverOfflineBtn").onclick = async () => {
  const driverId = document.getElementById("driverId").value;
  await api(
    `/drivers/${driverId}/offline`,
    "POST",
    commonContext(),
    "offline"
  );
};

document.getElementById("estimateFareBtn").onclick = async () => {
  const pickup = getSpot("pickupSpot");
  const drop = getSpot("dropSpot");
  const estimate = await api(
    "/rides/estimate",
    "POST",
    {
      ...commonContext(),
      pickup_lat: pickup.lat,
      pickup_lng: pickup.lng,
      destination_lat: drop.lat,
      destination_lng: drop.lng,
      tier: document.getElementById("tier").value,
    },
    "estimate",
    false
  );

  estimateResultEl.innerHTML = [
    `<strong>Route:</strong> ${pickup.name} -> ${drop.name}`,
    `<strong>Distance:</strong> ${estimate.distance_km} km | <strong>ETA:</strong> ~${estimate.eta_min} min`,
    `<strong>Fare without surge:</strong> Rs ${estimate.fare_without_surge}`,
    `<strong>Current surge:</strong> x${estimate.surge_multiplier} -> <strong>Payable now:</strong> Rs ${estimate.estimated_fare}`,
    `<strong>Proof:</strong> ${estimate.surge_explanation.active_requests} active requests / ${estimate.surge_explanation.available_drivers} available drivers`,
  ].join("<br>");
};

document.getElementById("createRideBtn").onclick = async () => {
  const pickup = getSpot("pickupSpot");
  const drop = getSpot("dropSpot");
  const ride = await api(
    "/rides",
    "POST",
    {
      ...commonContext(),
      rider_id: document.getElementById("riderId").value,
      pickup_lat: pickup.lat,
      pickup_lng: pickup.lng,
      destination_lat: drop.lat,
      destination_lng: drop.lng,
      tier: document.getElementById("tier").value,
      payment_method: document.getElementById("paymentMethod").value,
    },
    "ride"
  );

  document.getElementById("rideId").value = ride.id;
  if (ride.trip_id) document.getElementById("tripId").value = ride.trip_id;
};

document.getElementById("driverDeclineBtn").onclick = async () => {
  const driverId = document.getElementById("driverId").value;
  const out = await api(
    `/drivers/${driverId}/decline`,
    "POST",
    {
      ...commonContext(),
      ride_id: document.getElementById("rideId").value,
    },
    "decline"
  );

  const reassignment = out.reassignment || {};
  if (reassignment.trip_id) document.getElementById("tripId").value = reassignment.trip_id;
};

document.getElementById("tripStartBtn").onclick = async () => {
  const tripId = document.getElementById("tripId").value;
  await api(`/trips/${tripId}/start`, "POST", commonContext(), "trip-start");
};

document.getElementById("tripEndBtn").onclick = async () => {
  const tripId = document.getElementById("tripId").value;
  await api(`/trips/${tripId}/end`, "POST", commonContext(), "trip-end");
};

document.getElementById("payBtn").onclick = async () => {
  await api(
    "/payments",
    "POST",
    {
      ...commonContext(),
      ride_id: document.getElementById("rideId").value,
    },
    "pay"
  );
};

document.getElementById("connectEventsBtn").onclick = () => {
  const tenant = document.getElementById("tenant").value;
  const source = new EventSource(`${API}/stream?tenant_id=${encodeURIComponent(tenant)}`);
  source.onmessage = (event) => {
    try {
      log({ stream: JSON.parse(event.data) });
    } catch {
      log({ stream: event.data });
    }
  };
  source.onerror = () => log("stream disconnected");
  log(`stream connected for tenant=${tenant}`);
};
