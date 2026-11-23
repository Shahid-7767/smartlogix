const USER_ROLE = document.body.dataset.role || "faculty";
let overviewChart, twinChart, pieChart, fogChart;
let leafletMap = null;
let routeLayer = null;

function showSection(secId, btn) {
  document.querySelectorAll(".panel").forEach(p => p.classList.remove("active"));
  document.querySelectorAll(".nav-btn").forEach(b => b.classList.remove("active"));
  document.getElementById("sec-" + secId).classList.add("active");
  btn.classList.add("active");
  document.getElementById("page-title").innerText = btn.innerText;
  if (secId === "routes") { setTimeout(() => { initMap(); loadOptimizedRoute(); }, 150); }
}

async function fetchDashboardData() {
  try {
    const res = await fetch("/api/overview");
    if (res.status === 401) { window.location.href = "/login"; return; }
    const data = await res.json();
    renderKPIs(data.kpis);
    renderShipments(data.shipments, data.vehicles);
    renderVehicles(data.vehicles);
    renderTwin(data.digital_twins, data.readings);
    renderFogNodes(data.fog_nodes);
    renderColdChainReadings(data.readings);
    renderAlerts(data.alerts);
    renderAnalytics(data.kpis, data.fog_nodes);
    document.getElementById("sync-status").innerText = "Synced: " + new Date().toLocaleTimeString();
  } catch (err) {
    document.getElementById("sync-status").innerText = "Reconnecting...";
  }
}

function renderKPIs(k) {
  document.getElementById("kpi-total").innerText = k.total_shipments;
  document.getElementById("kpi-transit").innerText = k.in_transit;
  document.getElementById("kpi-delivered").innerText = k.delivered;
  document.getElementById("kpi-vehicles").innerText = k.active_vehicles;
  document.getElementById("kpi-alerts").innerText = k.open_alerts;
  document.getElementById("kpi-temp").innerText = `${k.current_temp} °C`;
}

function renderShipments(shipments, vehicles) {
  const vehSelect = document.getElementById("sh-veh");
  if (vehSelect && vehSelect.options.length === 0) {
    vehicles.forEach(v => {
      const opt = document.createElement("option");
      opt.value = v.vehicle_code;
      opt.innerText = `${v.vehicle_code} (${v.driver_name})`;
      vehSelect.appendChild(opt);
    });
  }
  document.getElementById("shipments-tbody").innerHTML = shipments.map(s => {
    const badgeClass = s.status === "Delivered" ? "ok" : (s.status === "Delayed" ? "crit" : "warn");
    const actions = USER_ROLE === "faculty" ? `<span class="muted">Read-Only</span>` :
      `<button class="btn-sm btn-ok" onclick="updateShipmentStatus(${s.id}, 'Delivered')">Deliver</button>
       <button class="btn-sm btn-del" onclick="deleteShipment(${s.id})">Delete</button>`;
    return `<tr><td><strong>${s.tracking_id}</strong></td><td>${s.medicine_name}</td><td>${s.batch_number}</td><td>${s.origin} &rarr; ${s.destination}</td><td>${s.min_temp}°C – ${s.max_temp}°C</td><td>${s.vehicle_code || "-"}</td><td><span class="badge ${badgeClass}">${s.status}</span></td><td>${actions}</td></tr>`;
  }).join("");
}

function renderVehicles(vehicles) {
  document.getElementById("vehicles-tbody").innerHTML = vehicles.map(v => `<tr><td><strong>${v.vehicle_code}</strong></td><td>${v.driver_name}</td><td>${v.vehicle_type}</td><td><span class="badge ok">${v.status}</span></td><td>${v.current_lat}, ${v.current_lng}</td></tr>`).join("");
}

function renderTwin(twins, readings) {
  if (twins.length > 0) {
    const t = twins[0];
    document.getElementById("twin-status").innerText = `${t.status} (${t.source_type})`;
    document.getElementById("twin-temp").innerText = `${t.last_temp ?? "--"} °C`;
    document.getElementById("twin-hum").innerText = `${t.last_humidity ?? "--"} %`;
  }
  const labels = readings.map(r => r.recorded_at.split(" ")[1]);
  const temps = readings.map(r => r.temperature);
  const hums = readings.map(r => r.humidity);
  if (overviewChart) overviewChart.destroy();
  overviewChart = new Chart(document.getElementById("overviewTempChart"), {
    type: "line",
    data: { labels, datasets: [{ label: "Container Temp (°C)", data: temps, borderColor: "#38bdf8", backgroundColor: "rgba(56,189,248,0.15)", fill: true, tension: 0.3 }] },
    options: { plugins: { legend: { labels: { color: "#f8fafc" } } }, scales: { x: { ticks: { color: "#94a3b8" } }, y: { ticks: { color: "#94a3b8" } } } }
  });
  if (twinChart) twinChart.destroy();
  twinChart = new Chart(document.getElementById("twinHistoryChart"), {
    type: "line",
    data: { labels, datasets: [{ label: "Temperature (°C)", data: temps, borderColor: "#f59e0b", tension: 0.3 }, { label: "Humidity (%)", data: hums, borderColor: "#22c55e", tension: 0.3 }] },
    options: { plugins: { legend: { labels: { color: "#f8fafc" } } }, scales: { x: { ticks: { color: "#94a3b8" } }, y: { ticks: { color: "#94a3b8" } } } }
  });
}

function renderFogNodes(nodes) {
  const html = nodes.map(n => {
    const cls = n.status === "Offline" ? "crit" : (n.status.includes("Failover") ? "warn" : "ok");
    return `<div class="node-box"><div style="display:flex;justify-content:space-between;align-items:center;"><strong>${n.node_name}</strong><span class="badge ${cls}">${n.status}</span></div><p class="muted" style="margin-top:6px;">Role: ${n.role} | Endpoint: ${n.endpoint_url}</p><p style="margin-top:6px;font-size:0.88rem;">Packets Processed: <strong>${n.packets_processed}</strong> | Alerts Raised: <strong>${n.alerts_generated}</strong></p><small class="muted">Last Heartbeat: ${n.last_heartbeat || "Pending"}</small></div>`;
  }).join("");
  document.getElementById("fog-cards-grid").innerHTML = html;
  document.getElementById("overview-nodes-box").innerHTML = html;
}

function renderColdChainReadings(readings) {
  document.getElementById("readings-tbody").innerHTML = [...readings].reverse().map(r => `<tr><td>${r.recorded_at}</td><td>${r.twin_id}</td><td>${r.tracking_id}</td><td><strong>${r.temperature} °C</strong></td><td>${r.humidity} %</td><td><span class="badge ok">${r.processed_by_node}</span></td><td>${r.is_anomaly ? '<span class="badge crit">BREACH</span>' : '<span class="badge ok">SAFE (2-8°C)</span>'}</td></tr>`).join("");
}

function renderAlerts(alerts) {
  const open = alerts.filter(a => a.resolved === 0).slice(0, 3);
  document.getElementById("overview-alerts-box").innerHTML = open.length ? open.map(a => `<div class="alert-banner danger" style="margin-top:8px;"><strong>${a.alert_type}:</strong> ${a.message}</div>`).join("") : `<p class="muted" style="margin-top:8px;">No active cold-chain breaches.</p>`;
  document.getElementById("alerts-tbody").innerHTML = alerts.map(a => `<tr><td>${a.created_at}</td><td>${a.alert_type}</td><td><span class="badge ${a.severity === 'Critical' ? 'crit' : 'warn'}">${a.severity}</span></td><td>${a.tracking_id || a.node_id || "-"}</td><td>${a.message}</td><td>${a.resolved ? '<span class="badge ok">Resolved</span>' : (USER_ROLE === 'faculty' ? 'Open' : `<button class="btn-sm btn-ok" onclick="resolveAlert(${a.id})">Resolve</button>`)}</td></tr>`).join("");
}

function renderAnalytics(k, nodes) {
  if (pieChart) pieChart.destroy();
  pieChart = new Chart(document.getElementById("shipmentPieChart"), {
    type: "doughnut",
    data: { labels: ["In-Transit", "Delivered", "Delayed"], datasets: [{ data: [k.in_transit, k.delivered, k.delayed], backgroundColor: ["#38bdf8", "#22c55e", "#ef4444"] }] },
    options: { plugins: { legend: { labels: { color: "#f8fafc" } } } }
  });
  if (fogChart) fogChart.destroy();
  fogChart = new Chart(document.getElementById("fogBarChart"), {
    type: "bar",
    data: { labels: nodes.map(n => n.node_id), datasets: [{ label: "Packets Processed", data: nodes.map(n => n.packets_processed), backgroundColor: ["#38bdf8", "#f59e0b"] }] },
    options: { plugins: { legend: { labels: { color: "#f8fafc" } } }, scales: { x: { ticks: { color: "#94a3b8" } }, y: { ticks: { color: "#94a3b8" } } } }
  });
}

function initMap() {
  if (leafletMap) return;
  leafletMap = L.map("route-map").setView([12.9716, 77.5946], 11);
  L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", { attribution: "&copy; OpenStreetMap contributors" }).addTo(leafletMap);
  routeLayer = L.layerGroup().addTo(leafletMap);
}

async function loadOptimizedRoute() {
  initMap();
  const res = await fetch("/api/route-optimize");
  const data = await res.json();
  routeLayer.clearLayers();
  document.getElementById("route-summary").innerText = `Optimized Sequence: ${data.waypoints.length} stops | Total Distance: ${data.total_distance_km} km | Est. Cold-Chain Transit: ${data.estimated_minutes} mins`;
  const latlngs = [];
  const listHtml = data.waypoints.map(w => {
    latlngs.push([w.lat, w.lng]);
    L.marker([w.lat, w.lng]).addTo(routeLayer).bindPopup(`<strong>Stop ${w.order}:</strong> ${w.label}`);
    return `<li><strong>Stop ${w.order}:</strong> ${w.label} (${w.leg_km} km)</li>`;
  }).join("");
  if (latlngs.length > 1) {
    L.polyline(latlngs, { color: "#38bdf8", weight: 4 }).addTo(routeLayer);
    leafletMap.fitBounds(latlngs, { padding: [30, 30] });
  }
  document.getElementById("route-steps").innerHTML = listHtml;
}

const shForm = document.getElementById("shipment-form");
if (shForm) {
  shForm.addEventListener("submit", async (e) => {
    e.preventDefault();
    await fetch("/api/shipments", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        tracking_id: document.getElementById("sh-id").value,
        medicine_name: document.getElementById("sh-med").value,
        batch_number: document.getElementById("sh-batch").value,
        origin: document.getElementById("sh-origin").value,
        origin_lat: document.getElementById("sh-olat").value,
        origin_lng: document.getElementById("sh-olng").value,
        destination: document.getElementById("sh-dest").value,
        dest_lat: document.getElementById("sh-dlat").value,
        dest_lng: document.getElementById("sh-dlng").value,
        vehicle_code: document.getElementById("sh-veh").value,
        status: document.getElementById("sh-status").value
      })
    });
    shForm.reset();
    fetchDashboardData();
  });
}

const vForm = document.getElementById("vehicle-form");
if (vForm) {
  vForm.addEventListener("submit", async (e) => {
    e.preventDefault();
    await fetch("/api/vehicles", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        vehicle_code: document.getElementById("v-code").value,
        driver_name: document.getElementById("v-driver").value,
        vehicle_type: document.getElementById("v-type").value,
        status: document.getElementById("v-status").value
      })
    });
    vForm.reset();
    fetchDashboardData();
  });
}

async function updateShipmentStatus(id, status) {
  await fetch(`/api/shipments/${id}`, { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ status }) });
  fetchDashboardData();
}
async function deleteShipment(id) {
  await fetch(`/api/shipments/${id}`, { method: "DELETE" });
  fetchDashboardData();
}
async function resolveAlert(id) {
  await fetch(`/api/alerts/${id}/resolve`, { method: "POST" });
  fetchDashboardData();
}
fetchDashboardData();
setInterval(fetchDashboardData, 4000);

async function sendBenchTwinReading() {
  const t = parseFloat(document.getElementById("bt-temp-input").value);
  const h = parseFloat(document.getElementById("bt-hum-input").value || "50");
  if (isNaN(t)) { alert("Enter a valid temperature from BenchTwin!"); return; }
  await fetch("/api/fog/ingest", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      twin_id: "BT-ESP32-CONT-01",
      tracking_id: "SLX-1001",
      temperature: t,
      humidity: h,
      processed_by_node: "FOG-NODE-1",
      source_mode: "BenchTwin-ESP32-Live",
      is_anomaly: (t > 8.0 || t < 2.0),
      alerts: t > 8.0 ? [{ type: "Temperature Breach (High)", severity: "Critical", message: `CRITICAL HEAT EXCURSION on SLX-1001: ${t}°C exceeds 8.0°C limit!` }] : (t < 2.0 ? [{ type: "Temperature Breach (Freeze)", severity: "Critical", message: `CRITICAL FREEZE RISK on SLX-1001: ${t}°C dropped below 2.0°C!` }] : [])
    })
  });
  fetchDashboardData();
}

let twinPushTimer = null;
function onTwinSliderMove() {
  const t = parseFloat(document.getElementById("bt-temp-slider").value);
  const h = parseFloat(document.getElementById("bt-hum-slider").value);
  document.getElementById("bt-temp-val").innerText = `${t.toFixed(1)} °C`;
  document.getElementById("bt-hum-val").innerText = `${h.toFixed(0)} %`;
  clearTimeout(twinPushTimer);
  twinPushTimer = setTimeout(() => pushTwinSliderPacket(), 350);
}

async function pushTwinSliderPacket() {
  const slider = document.getElementById("bt-temp-slider");
  if (!slider) return;
  const t = parseFloat(slider.value);
  const h = parseFloat(document.getElementById("bt-hum-slider").value);
  await fetch("/api/fog/ingest", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      twin_id: "BT-ESP32-CONT-01",
      tracking_id: "SLX-1001",
      temperature: t,
      humidity: h,
      processed_by_node: "FOG-NODE-1",
      source_mode: "BenchTwin-ESP32-Live",
      is_anomaly: (t > 8.0 || t < 2.0),
      alerts: t > 8.0 ? [{ type: "Temperature Breach (High)", severity: "Critical", message: `CRITICAL HEAT EXCURSION on SLX-1001: ${t.toFixed(1)}°C exceeds 8.0°C!` }] : (t < 2.0 ? [{ type: "Temperature Breach (Freeze)", severity: "Critical", message: `CRITICAL FREEZE RISK on SLX-1001: ${t.toFixed(1)}°C below 2.0°C!` }] : [])
    })
  });
  fetchDashboardData();
}

setInterval(() => {
  const auto = document.getElementById("bt-auto-stream");
  if (auto && auto.checked) pushTwinSliderPacket();
}, 3000);
