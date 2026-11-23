import os
import math
from datetime import datetime
from functools import wraps
from flask import Flask, request, jsonify, render_template, session, redirect, url_for
from flask_cors import CORS
from werkzeug.security import check_password_hash
from database import get_db, init_db, rows_to_list

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
TEMPLATE_DIR = os.path.abspath(os.path.join(BASE_DIR, "..", "frontend", "templates"))
STATIC_DIR = os.path.abspath(os.path.join(BASE_DIR, "..", "frontend", "static"))

app = Flask(__name__, template_folder=TEMPLATE_DIR, static_folder=STATIC_DIR)
app.secret_key = os.environ.get("SECRET_KEY", "smartlogix-super-secret-key-2026")
FOG_API_KEY = os.environ.get("FOG_API_KEY", "smartlogix-fog-secret-token")

CORS(app)

# Initialize tables & default records on startup
init_db()


# ---------- AUTHENTICATION & ROLE-BASED ACCESS CONTROL ----------
def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if "user" not in session:
            if request.path.startswith("/api/"):
                return jsonify({"error": "Authentication required"}), 401
            return redirect(url_for("login_page"))
        return f(*args, **kwargs)
    return decorated


def write_access_required(f):
    """Blocks read-only Faculty users from modifying data."""
    @wraps(f)
    def decorated(*args, **kwargs):
        user = session.get("user")
        if not user:
            return jsonify({"error": "Authentication required"}), 401
        if user.get("role") == "faculty":
            return jsonify({"error": "Read-only Faculty account cannot modify records"}), 403
        return f(*args, **kwargs)
    return decorated


def fog_or_login_required(f):
    """Allows authenticated dashboard users OR trusted Fog Nodes via X-Fog-Key header."""
    @wraps(f)
    def decorated(*args, **kwargs):
        token = request.headers.get("X-Fog-Key")
        if token == FOG_API_KEY or "user" in session:
            return f(*args, **kwargs)
        return jsonify({"error": "Unauthorized telemetry source"}), 401
    return decorated


# ---------- WEB PAGE ROUTES ----------
@app.route("/login", methods=["GET", "POST"])
def login_page():
    if request.method == "POST":
        data = request.get_json(silent=True) or request.form
        username = (data.get("username") or "").strip().lower()
        password = data.get("password") or ""

        db = get_db()
        user = db.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
        db.close()

        if user and check_password_hash(user["password_hash"], password):
            session["user"] = {
                "id": user["id"],
                "username": user["username"],
                "role": user["role"],
                "full_name": user["full_name"]
            }
            if request.is_json:
                return jsonify({"status": "ok", "user": session["user"]})
            return redirect(url_for("dashboard_page"))

        if request.is_json:
            return jsonify({"error": "Invalid username or password"}), 401
        return render_template("login.html", error="Invalid username or password")

    return render_template("login.html")


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login_page"))


@app.route("/")
@login_required
def dashboard_page():
    return render_template("index.html", user=session["user"])


# ---------- OVERVIEW & ANALYTICS API ----------
@app.route("/api/overview", methods=["GET"])
@login_required
def get_overview():
    db = get_db()
    shipments = rows_to_list(db.execute("SELECT * FROM shipments ORDER BY id DESC").fetchall())
    vehicles = rows_to_list(db.execute("SELECT * FROM vehicles ORDER BY id DESC").fetchall())
    alerts = rows_to_list(db.execute("SELECT * FROM alerts ORDER BY id DESC LIMIT 30").fetchall())
    twins = rows_to_list(db.execute("SELECT * FROM digital_twins").fetchall())
    nodes = rows_to_list(db.execute("SELECT * FROM fog_nodes ORDER BY node_id ASC").fetchall())
    readings = rows_to_list(db.execute("SELECT * FROM sensor_readings ORDER BY id DESC LIMIT 25").fetchall())
    deliveries = rows_to_list(db.execute("SELECT * FROM delivery_records ORDER BY id DESC LIMIT 20").fetchall())
    db.close()

    total_shipments = len(shipments)
    in_transit = sum(1 for s in shipments if s["status"] == "In-Transit")
    delivered = sum(1 for s in shipments if s["status"] == "Delivered")
    delayed = sum(1 for s in shipments if s["status"] == "Delayed")
    active_vehicles = sum(1 for v in vehicles if v["status"] in ("In-Transit", "Available"))
    open_alerts = sum(1 for a in alerts if a["resolved"] == 0)
    current_temp = readings[0]["temperature"] if readings else (twins[0]["last_temp"] if twins else 4.5)
    current_hum = readings[0]["humidity"] if readings else (twins[0]["last_humidity"] if twins else 48.0)

    return jsonify({
        "kpis": {
            "total_shipments": total_shipments,
            "in_transit": in_transit,
            "delivered": delivered,
            "delayed": delayed,
            "active_vehicles": active_vehicles,
            "open_alerts": open_alerts,
            "current_temp": current_temp,
            "current_humidity": current_hum
        },
        "shipments": shipments,
        "vehicles": vehicles,
        "alerts": alerts,
        "digital_twins": twins,
        "fog_nodes": nodes,
        "readings": list(reversed(readings)),
        "deliveries": deliveries
    })


# ---------- SHIPMENT CRUD API ----------
@app.route("/api/shipments", methods=["GET", "POST"])
@login_required
def handle_shipments():
    db = get_db()
    if request.method == "GET":
        rows = rows_to_list(db.execute("SELECT * FROM shipments ORDER BY id DESC").fetchall())
        db.close()
        return jsonify(rows)

    if session["user"]["role"] == "faculty":
        db.close()
        return jsonify({"error": "Faculty account is read-only"}), 403

    data = request.get_json()
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    try:
        db.execute("""
            INSERT INTO shipments (
                tracking_id, medicine_name, batch_number, min_temp, max_temp,
                origin, origin_lat, origin_lng, destination, dest_lat, dest_lng,
                vehicle_code, status, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            data["tracking_id"].strip().upper(),
            data["medicine_name"].strip(),
            data.get("batch_number", "BATCH-NEW").strip(),
            float(data.get("min_temp", 2.0)),
            float(data.get("max_temp", 8.0)),
            data["origin"].strip(),
            float(data.get("origin_lat", 12.9716)),
            float(data.get("origin_lng", 77.5946)),
            data["destination"].strip(),
            float(data.get("dest_lat", 12.9352)),
            float(data.get("dest_lng", 77.6245)),
            data.get("vehicle_code", "KA-01-MX-4410"),
            data.get("status", "In-Transit"),
            now
        ))
        if data.get("status") == "Delayed":
            db.execute(
                "INSERT INTO alerts (alert_type, severity, tracking_id, message, created_at) VALUES (?, ?, ?, ?, ?)",
                ("Delivery Delay", "Warning", data["tracking_id"].strip().upper(),
                 f"Shipment {data['tracking_id']} flagged as Delayed.", now)
            )
        db.commit()
        db.close()
        return jsonify({"status": "created"}), 201
    except Exception as e:
        db.close()
        return jsonify({"error": str(e)}), 400


@app.route("/api/shipments/<int:shipment_id>", methods=["PUT", "DELETE"])
@write_access_required
def modify_shipment(shipment_id):
    db = get_db()
    if request.method == "DELETE":
        db.execute("DELETE FROM shipments WHERE id = ?", (shipment_id,))
        db.commit()
        db.close()
        return jsonify({"status": "deleted"})

    data = request.get_json()
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    existing = db.execute("SELECT * FROM shipments WHERE id = ?", (shipment_id,)).fetchone()
    if not existing:
        db.close()
        return jsonify({"error": "Shipment not found"}), 404

    new_status = data.get("status", existing["status"])
    new_vehicle = data.get("vehicle_code", existing["vehicle_code"])
    new_med = data.get("medicine_name", existing["medicine_name"])
    new_dest = data.get("destination", existing["destination"])

    db.execute("""
        UPDATE shipments
        SET medicine_name = ?, destination = ?, vehicle_code = ?, status = ?
        WHERE id = ?
    """, (new_med, new_dest, new_vehicle, new_status, shipment_id))

    if new_status == "Delivered":
        db.execute(
            "INSERT INTO delivery_records (tracking_id, vehicle_code, checkpoint, notes, recorded_at) VALUES (?, ?, ?, ?, ?)",
            (existing["tracking_id"], new_vehicle, new_dest, "Marked Delivered via Dashboard", now)
        )
    elif new_status == "Delayed":
        db.execute(
            "INSERT INTO alerts (alert_type, severity, tracking_id, message, created_at) VALUES (?, ?, ?, ?, ?)",
            ("Delivery Delay", "Warning", existing["tracking_id"],
             f"Shipment {existing['tracking_id']} experienced a route delay.", now)
        )

    db.commit()
    db.close()
    return jsonify({"status": "updated"})


# ---------- VEHICLE MANAGEMENT API ----------
@app.route("/api/vehicles", methods=["GET", "POST"])
@login_required
def handle_vehicles():
    db = get_db()
    if request.method == "GET":
        rows = rows_to_list(db.execute("SELECT * FROM vehicles ORDER BY id DESC").fetchall())
        db.close()
        return jsonify(rows)

    if session["user"]["role"] == "faculty":
        db.close()
        return jsonify({"error": "Faculty account is read-only"}), 403

    data = request.get_json()
    try:
        db.execute("""
            INSERT INTO vehicles (vehicle_code, driver_name, vehicle_type, status, current_lat, current_lng)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (
            data["vehicle_code"].strip().upper(),
            data["driver_name"].strip(),
            data.get("vehicle_type", "Refrigerated Reefer Van"),
            data.get("status", "Available"),
            float(data.get("current_lat", 12.9716)),
            float(data.get("current_lng", 77.5946))
        ))
        db.commit()
        db.close()
        return jsonify({"status": "created"}), 201
    except Exception as e:
        db.close()
        return jsonify({"error": str(e)}), 400


# ---------- FOG TELEMETRY & HEARTBEAT INGESTION API ----------
@app.route("/api/fog/ingest", methods=["POST"])
@fog_or_login_required
def ingest_fog_processed_data():
    """Receives pre-processed, threshold-checked packets from Fog Node 1 or Fog Node 2."""
    data = request.get_json()
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    twin_id = data.get("twin_id", "BT-ESP32-CONT-01")
    tracking_id = data.get("tracking_id", "SLX-1001")
    temperature = float(data["temperature"])
    humidity = float(data["humidity"])
    node_id = data.get("processed_by_node", "FOG-NODE-1")
    source_mode = data.get("source_mode", "BenchTwin-ESP32")
    is_anomaly = 1 if data.get("is_anomaly") else 0
    alert_messages = data.get("alerts", [])

    db = get_db()
    db.execute("""
        INSERT INTO sensor_readings (twin_id, tracking_id, temperature, humidity, processed_by_node, source_mode, is_anomaly, recorded_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (twin_id, tracking_id, temperature, humidity, node_id, source_mode, is_anomaly, now))

    db.execute("""
        UPDATE digital_twins
        SET status = 'Online', source_type = ?, last_temp = ?, last_humidity = ?, last_seen = ?
        WHERE twin_id = ?
    """, (source_mode, temperature, humidity, now, twin_id))

    db.execute("""
        UPDATE fog_nodes
        SET status = 'Online', packets_processed = packets_processed + 1,
            alerts_generated = alerts_generated + ?, last_heartbeat = ?
        WHERE node_id = ?
    """, (len(alert_messages), now, node_id))

    for alert in alert_messages:
        db.execute("""
            INSERT INTO alerts (alert_type, severity, tracking_id, node_id, message, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (
            alert.get("type", "Cold-Chain Breach"),
            alert.get("severity", "Critical"),
            tracking_id,
            node_id,
            alert["message"],
            now
        ))

    db.commit()
    db.close()
    return jsonify({"status": "stored", "node": node_id, "anomaly": bool(is_anomaly)})


@app.route("/api/fog/status", methods=["POST"])
@fog_or_login_required
def update_fog_status():
    """Updates Fog Node heartbeat or records failover events."""
    data = request.get_json()
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    node_id = data["node_id"]
    status = data["status"]
    failover_msg = data.get("failover_alert")

    db = get_db()
    db.execute("UPDATE fog_nodes SET status = ?, last_heartbeat = ? WHERE node_id = ?", (status, now, node_id))
    if failover_msg:
        db.execute("""
            INSERT INTO alerts (alert_type, severity, node_id, message, created_at)
            VALUES (?, ?, ?, ?, ?)
        """, ("Fog Node Failover", "Critical", node_id, failover_msg, now))
    db.commit()
    db.close()
    return jsonify({"status": "updated"})


@app.route("/api/alerts/<int:alert_id>/resolve", methods=["POST"])
@write_access_required
def resolve_alert(alert_id):
    db = get_db()
    db.execute("UPDATE alerts SET resolved = 1 WHERE id = ?", (alert_id,))
    db.commit()
    db.close()
    return jsonify({"status": "resolved"})


# ---------- ROUTE OPTIMIZATION API (GREEDY NEAREST-NEIGHBOR) ----------
def haversine_km(lat1, lon1, lat2, lon2):
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return r * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


@app.route("/api/route-optimize", methods=["GET"])
@login_required
def optimize_route():
    db = get_db()
    active_shipments = rows_to_list(
        db.execute("SELECT * FROM shipments WHERE status != 'Delivered'").fetchall()
    )
    db.close()

    if not active_shipments:
        return jsonify({"waypoints": [], "total_distance_km": 0, "estimated_minutes": 0})

    # Start at first shipment origin hub, visit all destinations using nearest-neighbor heuristic
    curr_lat = active_shipments[0]["origin_lat"]
    curr_lng = active_shipments[0]["origin_lng"]
    waypoints = [{
        "order": 1,
        "label": f"Hub: {active_shipments[0]['origin']}",
        "tracking_id": active_shipments[0]["tracking_id"],
        "lat": curr_lat,
        "lng": curr_lng,
        "leg_km": 0.0
    }]

    unvisited = list(active_shipments)
    total_km = 0.0
    step = 2

    while unvisited:
        nearest = min(unvisited, key=lambda s: haversine_km(curr_lat, curr_lng, s["dest_lat"], s["dest_lng"]))
        dist = round(haversine_km(curr_lat, curr_lng, nearest["dest_lat"], nearest["dest_lng"]), 2)
        total_km += dist
        waypoints.append({
            "order": step,
            "label": f"Drop ({nearest['tracking_id']}): {nearest['destination']}",
            "tracking_id": nearest["tracking_id"],
            "lat": nearest["dest_lat"],
            "lng": nearest["dest_lng"],
            "leg_km": dist
        })
        curr_lat, curr_lng = nearest["dest_lat"], nearest["dest_lng"]
        unvisited.remove(nearest)
        step += 1

    est_minutes = round((total_km / 28.0) * 60)  # Avg urban cold-chain speed 28 km/h
    return jsonify({
        "waypoints": waypoints,
        "total_distance_km": round(total_km, 2),
        "estimated_minutes": est_minutes
    })


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=True)