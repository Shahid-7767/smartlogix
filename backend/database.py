import os
import sqlite3
from datetime import datetime
from werkzeug.security import generate_password_hash

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "smartlogix.db")
DATABASE_URL = os.environ.get("DATABASE_URL")  # Used automatically when deployed to Render PostgreSQL

USE_POSTGRES = bool(DATABASE_URL and DATABASE_URL.startswith("postgres"))

if USE_POSTGRES:
    import psycopg2
    import psycopg2.extras


class DBConnection:
    """Unified wrapper so identical SQL works on both local SQLite and hosted PostgreSQL."""
    def __init__(self, conn):
        self.conn = conn

    def _adapt_sql(self, sql):
        if USE_POSTGRES:
            return sql.replace("?", "%s")
        return sql

    def execute(self, sql, params=()):
        adapted = self._adapt_sql(sql)
        if USE_POSTGRES:
            cur = self.conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            cur.execute(adapted, params)
            return cur
        else:
            cur = self.conn.cursor()
            cur.execute(adapted, params)
            return cur

    def commit(self):
        self.conn.commit()

    def close(self):
        self.conn.close()


def get_db():
    if USE_POSTGRES:
        conn = psycopg2.connect(DATABASE_URL)
        return DBConnection(conn)
    else:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        return DBConnection(conn)


def rows_to_list(rows):
    return [dict(row) for row in rows]


def init_db():
    db = get_db()
    id_col = "SERIAL PRIMARY KEY" if USE_POSTGRES else "INTEGER PRIMARY KEY AUTOINCREMENT"

    # 1. Users table (Role-Based Access Control: admin, team, faculty)
    db.execute(f"""
        CREATE TABLE IF NOT EXISTS users (
            id {id_col},
            username TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            role TEXT NOT NULL,
            full_name TEXT NOT NULL
        )
    """)

    # 2. Vehicles table
    db.execute(f"""
        CREATE TABLE IF NOT EXISTS vehicles (
            id {id_col},
            vehicle_code TEXT UNIQUE NOT NULL,
            driver_name TEXT NOT NULL,
            vehicle_type TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'Available',
            current_lat REAL NOT NULL,
            current_lng REAL NOT NULL
        )
    """)

    # 3. Shipments table
    db.execute(f"""
        CREATE TABLE IF NOT EXISTS shipments (
            id {id_col},
            tracking_id TEXT UNIQUE NOT NULL,
            medicine_name TEXT NOT NULL,
            batch_number TEXT NOT NULL,
            min_temp REAL NOT NULL DEFAULT 2.0,
            max_temp REAL NOT NULL DEFAULT 8.0,
            origin TEXT NOT NULL,
            origin_lat REAL NOT NULL,
            origin_lng REAL NOT NULL,
            destination TEXT NOT NULL,
            dest_lat REAL NOT NULL,
            dest_lng REAL NOT NULL,
            vehicle_code TEXT,
            status TEXT NOT NULL DEFAULT 'In-Transit',
            created_at TEXT NOT NULL
        )
    """)

    # 4. Digital Twin Devices table (BenchTwin ESP32 + DHT22 representation)
    db.execute(f"""
        CREATE TABLE IF NOT EXISTS digital_twins (
            id {id_col},
            twin_id TEXT UNIQUE NOT NULL,
            container_name TEXT NOT NULL,
            shipment_tracking_id TEXT,
            source_type TEXT NOT NULL DEFAULT 'BenchTwin-ESP32',
            status TEXT NOT NULL DEFAULT 'Online',
            last_temp REAL,
            last_humidity REAL,
            last_seen TEXT
        )
    """)

    # 5. Fog Nodes table
    db.execute(f"""
        CREATE TABLE IF NOT EXISTS fog_nodes (
            id {id_col},
            node_id TEXT UNIQUE NOT NULL,
            node_name TEXT NOT NULL,
            endpoint_url TEXT NOT NULL,
            role TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'Online',
            packets_processed INTEGER NOT NULL DEFAULT 0,
            alerts_generated INTEGER NOT NULL DEFAULT 0,
            last_heartbeat TEXT
        )
    """)

    # 6. Sensor Readings table
    db.execute(f"""
        CREATE TABLE IF NOT EXISTS sensor_readings (
            id {id_col},
            twin_id TEXT NOT NULL,
            tracking_id TEXT NOT NULL,
            temperature REAL NOT NULL,
            humidity REAL NOT NULL,
            processed_by_node TEXT NOT NULL,
            source_mode TEXT NOT NULL,
            is_anomaly INTEGER NOT NULL DEFAULT 0,
            recorded_at TEXT NOT NULL
        )
    """)

    # 7. Alerts table
    db.execute(f"""
        CREATE TABLE IF NOT EXISTS alerts (
            id {id_col},
            alert_type TEXT NOT NULL,
            severity TEXT NOT NULL,
            tracking_id TEXT,
            node_id TEXT,
            message TEXT NOT NULL,
            resolved INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL
        )
    """)

    # 8. Delivery Records table
    db.execute(f"""
        CREATE TABLE IF NOT EXISTS delivery_records (
            id {id_col},
            tracking_id TEXT NOT NULL,
            vehicle_code TEXT NOT NULL,
            checkpoint TEXT NOT NULL,
            notes TEXT,
            recorded_at TEXT NOT NULL
        )
    """)

    db.commit()

    # Seed initial users if empty
    existing_users = db.execute("SELECT COUNT(*) AS cnt FROM users").fetchone()
    count_val = existing_users["cnt"] if isinstance(existing_users, dict) else existing_users[0]
    if count_val == 0:
        default_users = [
            ("admin", generate_password_hash("Admin@123"), "admin", "Logistics Administrator"),
            ("team", generate_password_hash("Team@123"), "team", "Cold-Chain Operations Team"),
            ("faculty", generate_password_hash("Faculty@123"), "faculty", "Academic Evaluator (Read-Only)")
        ]
        for u, p, r, fn in default_users:
            db.execute(
                "INSERT INTO users (username, password_hash, role, full_name) VALUES (?, ?, ?, ?)",
                (u, p, r, fn)
            )

    # Seed initial vehicles if empty
    existing_veh = db.execute("SELECT COUNT(*) AS cnt FROM vehicles").fetchone()
    veh_cnt = existing_veh["cnt"] if isinstance(existing_veh, dict) else existing_veh[0]
    if veh_cnt == 0:
        vehicles = [
            ("KA-01-MX-4410", "Ramesh Kumar", "Refrigerated Reefer Van", "In-Transit", 12.9716, 77.5946),
            ("KA-05-TR-8821", "Suresh Gowda", "Cryo-Insulated Truck", "In-Transit", 13.0358, 77.5970),
            ("KA-53-CL-1109", "Arun Nair", "Cold-Chain Mini Van", "Available", 12.9279, 77.6271)
        ]
        for vc, dn, vt, st, lat, lng in vehicles:
            db.execute(
                "INSERT INTO vehicles (vehicle_code, driver_name, vehicle_type, status, current_lat, current_lng) VALUES (?, ?, ?, ?, ?, ?)",
                (vc, dn, vt, st, lat, lng)
            )

    # Seed initial shipments if empty
    existing_ship = db.execute("SELECT COUNT(*) AS cnt FROM shipments").fetchone()
    ship_cnt = existing_ship["cnt"] if isinstance(existing_ship, dict) else existing_ship[0]
    if ship_cnt == 0:
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        shipments = [
            ("SLX-1001", "Insulin Glargine 100IU", "BATCH-INS-09", 2.0, 8.0,
             "Biocon Biologics Hub, Electronic City", 12.8452, 77.6602,
             "Manipal Hospital, Old Airport Rd", 12.9592, 77.6484,
             "KA-01-MX-4410", "In-Transit", now),
            ("SLX-1002", "mRNA Vaccine Cold-Pack", "BATCH-VAC-22", 2.0, 8.0,
             "Peenya Pharma Depot, Bengaluru", 13.0285, 77.5197,
             "Aster CMI Hospital, Hebbal", 13.0544, 77.5916,
             "KA-05-TR-8821", "In-Transit", now),
            ("SLX-1003", "Albumin Serum 20%", "BATCH-ALB-04", 2.0, 8.0,
             "Whitefield Bio-Warehouse", 12.9698, 77.7500,
             "Apollo Hospital, Bannerghatta Rd", 12.8958, 77.5986,
             "KA-53-CL-1109", "Delivered", now)
        ]
        for s in shipments:
            db.execute("""
                INSERT INTO shipments (
                    tracking_id, medicine_name, batch_number, min_temp, max_temp,
                    origin, origin_lat, origin_lng, destination, dest_lat, dest_lng,
                    vehicle_code, status, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, s)

        db.execute(
            "INSERT INTO delivery_records (tracking_id, vehicle_code, checkpoint, notes, recorded_at) VALUES (?, ?, ?, ?, ?)",
            ("SLX-1003", "KA-53-CL-1109", "Apollo Hospital Receiving Dock", "Delivered within 2-8C cold-chain SLA", now)
        )

    # Seed Digital Twin & Fog Nodes
    existing_twin = db.execute("SELECT COUNT(*) AS cnt FROM digital_twins").fetchone()
    twin_cnt = existing_twin["cnt"] if isinstance(existing_twin, dict) else existing_twin[0]
    if twin_cnt == 0:
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        db.execute("""
            INSERT INTO digital_twins (twin_id, container_name, shipment_tracking_id, source_type, status, last_temp, last_humidity, last_seen)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, ("BT-ESP32-CONT-01", "Reefer Container #1 (ESP32 + DHT22)", "SLX-1001", "BenchTwin-ESP32", "Online", 4.6, 48.0, now))

    existing_nodes = db.execute("SELECT COUNT(*) AS cnt FROM fog_nodes").fetchone()
    node_cnt = existing_nodes["cnt"] if isinstance(existing_nodes, dict) else existing_nodes[0]
    if node_cnt == 0:
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        db.execute("""
            INSERT INTO fog_nodes (node_id, node_name, endpoint_url, role, status, packets_processed, alerts_generated, last_heartbeat)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, ("FOG-NODE-1", "Primary Edge Fog Node (Port 5001)", "http://127.0.0.1:5001", "Primary", "Online", 0, 0, now))
        db.execute("""
            INSERT INTO fog_nodes (node_id, node_name, endpoint_url, role, status, packets_processed, alerts_generated, last_heartbeat)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, ("FOG-NODE-2", "Secondary Failover Fog Node (Port 5002)", "http://127.0.0.1:5002", "Secondary", "Standby", 0, 0, now))

    db.commit()
    db.close()