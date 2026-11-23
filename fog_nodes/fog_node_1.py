import os
import time
from collections import deque
from datetime import datetime
from flask import Flask, request, jsonify
import requests

app = Flask(__name__)

NODE_ID = "FOG-NODE-1"
PORT = 5001
CLOUD_URL = os.environ.get("CLOUD_URL", "http://127.0.0.1:5000")
FOG_API_KEY = os.environ.get("FOG_API_KEY", "smartlogix-fog-secret-token")

# Local cold-chain SLA thresholds (WHO pharmaceutical guidelines: 2C to 8C)
TEMP_MIN = 2.0
TEMP_MAX = 8.0
HUM_MIN = 30.0
HUM_MAX = 65.0

recent_temps = deque(maxlen=3)
stats = {
    "node_id": NODE_ID,
    "role": "Primary",
    "status": "Online",
    "packets_processed": 0,
    "alerts_generated": 0,
    "started_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
}


def log(msg):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] [{NODE_ID}] {msg}", flush=True)


def evaluate_cold_chain(temp, hum, tracking_id):
    alerts = []
    if temp > TEMP_MAX:
        alerts.append({
            "type": "Temperature Breach (High)",
            "severity": "Critical",
            "message": f"CRITICAL HEAT EXCURSION on {tracking_id}: {temp}°C exceeds {TEMP_MAX}°C limit!"
        })
    elif temp < TEMP_MIN:
        alerts.append({
            "type": "Temperature Breach (Freeze)",
            "severity": "Critical",
            "message": f"CRITICAL FREEZE RISK on {tracking_id}: {temp}°C dropped below {TEMP_MIN}°C!"
        })

    if hum > HUM_MAX or hum < HUM_MIN:
        alerts.append({
            "type": "Humidity Warning",
            "severity": "Warning",
            "message": f"HUMIDITY DEVIATION on {tracking_id}: {hum}% RH outside {HUM_MIN}-{HUM_MAX}% range."
        })
    return alerts


@app.route("/health", methods=["GET"])
def health():
    return jsonify(stats), 200


@app.route("/ingest", methods=["POST"])
def process_sensor_data():
    raw = request.get_json()
    raw_temp = float(raw["temperature"])
    raw_hum = float(raw["humidity"])
    twin_id = raw.get("twin_id", "BT-ESP32-CONT-01")
    tracking_id = raw.get("tracking_id", "SLX-1001")
    source_mode = raw.get("source_mode", "BenchTwin-ESP32")

    # Local Edge Processing: Moving-average smoothing + cold-chain threshold check
    recent_temps.append(raw_temp)
    smoothed_temp = round(sum(recent_temps) / len(recent_temps), 2)
    # Keep exact spike value if out of bounds so alerts trigger instantaneously
    effective_temp = raw_temp if (raw_temp > TEMP_MAX or raw_temp < TEMP_MIN) else smoothed_temp

    alerts = evaluate_cold_chain(effective_temp, raw_hum, tracking_id)
    is_anomaly = len(alerts) > 0

    stats["packets_processed"] += 1
    stats["alerts_generated"] += len(alerts)

    log(f"Processed {twin_id} ({tracking_id}) | Temp={effective_temp}°C, Hum={raw_hum}% | Anomaly={is_anomaly}")

    payload = {
        "twin_id": twin_id,
        "tracking_id": tracking_id,
        "temperature": effective_temp,
        "humidity": raw_hum,
        "processed_by_node": NODE_ID,
        "source_mode": source_mode,
        "is_anomaly": is_anomaly,
        "alerts": alerts
    }

    try:
        resp = requests.post(
            f"{CLOUD_URL}/api/fog/ingest",
            json=payload,
            headers={"X-Fog-Key": FOG_API_KEY},
            timeout=4
        )
        return jsonify({"status": "processed_by_node_1", "cloud_status": resp.status_code, "anomaly": is_anomaly}), 200
    except Exception as e:
        log(f"Cloud forward warning: {e}")
        return jsonify({"status": "processed_locally_cloud_offline", "anomaly": is_anomaly}), 202


if __name__ == "__main__":
    log(f"Starting Primary Fog Node on http://127.0.0.1:{PORT}")
    try:
        requests.post(
            f"{CLOUD_URL}/api/fog/status",
            json={"node_id": NODE_ID, "status": "Online"},
            headers={"X-Fog-Key": FOG_API_KEY},
            timeout=2
        )
    except Exception:
        pass
    app.run(host="0.0.0.0", port=PORT, debug=False)