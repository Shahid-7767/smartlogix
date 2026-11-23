import os
import time
import threading
from datetime import datetime
from flask import Flask, request, jsonify
import requests

app = Flask(__name__)

NODE_ID = "FOG-NODE-2"
PORT = 5002
PRIMARY_NODE_URL = os.environ.get("PRIMARY_NODE_URL", "http://127.0.0.1:5001")
CLOUD_URL = os.environ.get("CLOUD_URL", "http://127.0.0.1:5000")
FOG_API_KEY = os.environ.get("FOG_API_KEY", "smartlogix-fog-secret-token")

TEMP_MIN = 2.0
TEMP_MAX = 8.0
HUM_MIN = 30.0
HUM_MAX = 65.0

state = {
    "node_id": NODE_ID,
    "role": "Secondary",
    "status": "Standby",
    "primary_alive": True,
    "packets_processed": 0,
    "alerts_generated": 0
}


def log(msg):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] [{NODE_ID}] {msg}", flush=True)


def notify_cloud_status(target_node_id, status_text, failover_alert=None):
    try:
        body = {"node_id": target_node_id, "status": status_text}
        if failover_alert:
            body["failover_alert"] = failover_alert
        requests.post(
            f"{CLOUD_URL}/api/fog/status",
            json=body,
            headers={"X-Fog-Key": FOG_API_KEY},
            timeout=3
        )
    except Exception:
        pass


def monitor_primary_heartbeat():
    """Continuously monitors Fog Node 1; triggers automatic failover if Node 1 goes offline."""
    while True:
        try:
            r = requests.get(f"{PRIMARY_NODE_URL}/health", timeout=2)
            if r.status_code == 200:
                if not state["primary_alive"]:
                    log("RECOVERY DETECTED: FOG-NODE-1 is back online! Returning FOG-NODE-2 to Standby.")
                    state["primary_alive"] = True
                    state["status"] = "Standby"
                    notify_cloud_status("FOG-NODE-1", "Online")
                    notify_cloud_status("FOG-NODE-2", "Standby")
        except Exception:
            if state["primary_alive"]:
                log("FAILOVER TRIGGERED: FOG-NODE-1 unreachable! FOG-NODE-2 taking over workload.")
                state["primary_alive"] = False
                state["status"] = "Active (Failover)"
                notify_cloud_status(
                    "FOG-NODE-1",
                    "Offline",
                    failover_alert="FAILOVER EVENT: Primary FOG-NODE-1 failed! Secondary FOG-NODE-2 automatically assumed edge workload."
                )
                notify_cloud_status("FOG-NODE-2", "Active (Failover)")
        time.sleep(3)


def evaluate_cold_chain(temp, hum, tracking_id):
    alerts = []
    if temp > TEMP_MAX:
        alerts.append({
            "type": "Temperature Breach (High)",
            "severity": "Critical",
            "message": f"[FAILOVER NODE] CRITICAL HEAT on {tracking_id}: {temp}°C exceeds {TEMP_MAX}°C!"
        })
    elif temp < TEMP_MIN:
        alerts.append({
            "type": "Temperature Breach (Freeze)",
            "severity": "Critical",
            "message": f"[FAILOVER NODE] CRITICAL FREEZE on {tracking_id}: {temp}°C below {TEMP_MIN}°C!"
        })
    if hum > HUM_MAX or hum < HUM_MIN:
        alerts.append({
            "type": "Humidity Warning",
            "severity": "Warning",
            "message": f"[FAILOVER NODE] HUMIDITY WARNING on {tracking_id}: {hum}% RH out of range."
        })
    return alerts


@app.route("/health", methods=["GET"])
def health():
    return jsonify(state), 200


@app.route("/ingest", methods=["POST"])
def process_failover_data():
    raw = request.get_json()
    temp = float(raw["temperature"])
    hum = float(raw["humidity"])
    twin_id = raw.get("twin_id", "BT-ESP32-CONT-01")
    tracking_id = raw.get("tracking_id", "SLX-1001")
    source_mode = raw.get("source_mode", "BenchTwin-ESP32")

    alerts = evaluate_cold_chain(temp, hum, tracking_id)
    is_anomaly = len(alerts) > 0

    state["status"] = "Active (Failover)"
    state["packets_processed"] += 1
    state["alerts_generated"] += len(alerts)

    log(f"[FAILOVER PROCESSING] {twin_id} ({tracking_id}) | Temp={temp}°C, Hum={hum}% | Anomaly={is_anomaly}")

    payload = {
        "twin_id": twin_id,
        "tracking_id": tracking_id,
        "temperature": temp,
        "humidity": hum,
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
        return jsonify({"status": "processed_by_node_2_failover", "cloud_status": resp.status_code}), 200
    except Exception as e:
        log(f"Cloud forward error: {e}")
        return jsonify({"status": "queued_locally"}), 202


if __name__ == "__main__":
    log(f"Starting Secondary Failover Fog Node on http://127.0.0.1:{PORT}")
    notify_cloud_status(NODE_ID, "Standby")
    t = threading.Thread(target=monitor_primary_heartbeat, daemon=True)
    t.start()
    app.run(host="0.0.0.0", port=PORT, debug=False)