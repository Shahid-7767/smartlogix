import sys
import json
import time
import random
import threading
from datetime import datetime
import requests

FOG_NODE_1_URL = "http://127.0.0.1:5001/ingest"
FOG_NODE_2_URL = "http://127.0.0.1:5002/ingest"

TWIN_ID = "BT-ESP32-CONT-01"
TRACKING_ID = "SLX-1001"

mode = "NORMAL"  # NORMAL, HEAT_BREACH, FREEZE_BREACH
running = True


def log(msg):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] [DIGITAL-TWIN] {msg}", flush=True)


def forward_to_fog(temp, hum, source_mode):
    """Sends Digital Twin telemetry to Primary Fog Node 1; automatically fails over to Fog Node 2."""
    packet = {
        "twin_id": TWIN_ID,
        "tracking_id": TRACKING_ID,
        "temperature": round(temp, 2),
        "humidity": round(hum, 2),
        "source_mode": source_mode
    }
    try:
        r = requests.post(FOG_NODE_1_URL, json=packet, timeout=2)
        if r.status_code in (200, 202):
            log(f"Sent ({source_mode}) -> FOG-NODE-1 | Temp={packet['temperature']}°C, Hum={packet['humidity']}%")
            return
    except Exception:
        log("FOG-NODE-1 unreachable! Routing Digital Twin packet to FOG-NODE-2 (Failover)...")

    try:
        r2 = requests.post(FOG_NODE_2_URL, json=packet, timeout=2)
        if r2.status_code in (200, 202):
            log(f"Sent ({source_mode}) -> FOG-NODE-2 [FAILOVER] | Temp={packet['temperature']}°C, Hum={packet['humidity']}%")
    except Exception as e:
        log(f"ERROR: Both Fog Nodes unreachable ({e}). Start fog_node_1.py or fog_node_2.py!")


def run_benchtwin_serial(com_port, baud=115200):
    """Reads live JSON telemetry emitted by BenchTwin's virtual ESP32 + DHT22 UART output."""
    import serial
    log(f"Connecting to BenchTwin Virtual Serial Port {com_port} @ {baud} baud...")
    ser = serial.Serial(com_port, baud, timeout=2)
    log("Connected to BenchTwin! Streaming ESP32 + DHT22 readings to Fog Layer...")
    while running:
        line = ser.readline().decode("utf-8", errors="ignore").strip()
        if not line:
            continue
        try:
            # Expects ESP32 Serial.println("{\"temp\":4.6,\"hum\":48.5}");
            data = json.loads(line)
            temp = float(data.get("temp") or data.get("temperature"))
            hum = float(data.get("hum") or data.get("humidity"))
            forward_to_fog(temp, hum, "BenchTwin-ESP32-Live")
        except Exception:
            log(f"Raw BenchTwin serial line: {line}")


def run_twin_simulator():
    """Simulates the BenchTwin ESP32 + DHT22 container telemetry with interactive breach triggers."""
    global mode
    log("BenchTwin Digital Twin Bridge & Cold-Chain Simulator started.")
    log("Controls: Press [1] Normal (2-8°C) | [2] Heat Breach (>8°C) | [3] Freeze Breach (<2°C) + Enter")
    while running:
        if mode == "NORMAL":
            temp = random.uniform(3.8, 6.2)
            hum = random.uniform(44.0, 54.0)
        elif mode == "HEAT_BREACH":
            temp = random.uniform(9.5, 12.8)
            hum = random.uniform(68.0, 76.0)
        else:
            temp = random.uniform(0.2, 1.4)
            hum = random.uniform(35.0, 42.0)

        forward_to_fog(temp, hum, "BenchTwin-ESP32-Twin")
        time.sleep(4)


def keyboard_listener():
    global mode, running
    while running:
        cmd = input().strip()
        if cmd == "1":
            mode = "NORMAL"
            log(">>> Switched Digital Twin state to NORMAL COLD-CHAIN (2°C - 8°C)")
        elif cmd == "2":
            mode = "HEAT_BREACH"
            log(">>> Switched Digital Twin state to HEAT EXCURSION (> 8°C)!")
        elif cmd == "3":
            mode = "FREEZE_BREACH"
            log(">>> Switched Digital Twin state to FREEZE BREACH (< 2°C)!")


if __name__ == "__main__":
    # Usage:
    #   python digital_twin/twin_bridge.py              -> Runs Digital Twin simulator mode
    #   python digital_twin/twin_bridge.py COM3         -> Bridges real BenchTwin Serial UART port COM3
    if len(sys.argv) > 1 and sys.argv[1].upper().startswith("COM"):
        run_benchtwin_serial(sys.argv[1].upper())
    else:
        threading.Thread(target=keyboard_listener, daemon=True).start()
        run_twin_simulator()