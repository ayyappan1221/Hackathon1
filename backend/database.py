"""
EleGuard AI - SQLite Database Layer
Uses Python stdlib sqlite3 only (no extra deps) so it works out-of-the-box.
Creates eleguard.db next to main.py and provides helpers used by main.py.

Tables:
  sensor_readings      - every POST /api/sensors
  detections           - latest detection snapshot (one row per POST /api/detection, capped)
  detection_history    - deduped history for heatmap/prediction (max 300, mirrored in memory)
  human_sightings      - per-human sightings (max 200)
  alert_history        - risk state changes (max 200, + false alarms)
  nodes                - last_seen / health per node_id
  system_config        - kv for camera_mode etc.

Call init_db() once at startup. All helpers are safe to call even if DB file missing.
"""

import sqlite3
import json
import os
from datetime import datetime
from pathlib import Path
from contextlib import contextmanager

DB_PATH = Path(__file__).parent / "eleguard.db"
# Keep history bounded same as in-memory constants
MAX_DETECTION_HISTORY = 300
MAX_HUMAN_HISTORY = 200
MAX_ALERT_HISTORY = 200
MAX_SENSOR_ROWS_PER_NODE = 500  # prevent unbounded growth

SCHEMA = """
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS sensor_readings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    node_id TEXT NOT NULL,
    motion INTEGER NOT NULL,
    vibration INTEGER NOT NULL,
    temperature REAL NOT NULL,
    battery INTEGER NOT NULL,
    buzzer INTEGER NOT NULL,
    led INTEGER NOT NULL,
    power_source TEXT NOT NULL DEFAULT 'SOLAR',
    node_health TEXT NOT NULL DEFAULT 'UNKNOWN',
    timestamp TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_sensor_node_time ON sensor_readings(node_id, timestamp DESC);

CREATE TABLE IF NOT EXISTS detections (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    elephant_detected INTEGER NOT NULL,
    elephant_count INTEGER NOT NULL,
    elephant_confidence REAL NOT NULL,
    human_detected INTEGER NOT NULL,
    human_count INTEGER NOT NULL,
    vehicle_detected INTEGER NOT NULL,
    vehicle_count INTEGER NOT NULL,
    movement TEXT NOT NULL,
    location TEXT NOT NULL,
    x_position REAL NOT NULL,
    y_position REAL NOT NULL,
    primary_elephant_id TEXT,
    elephants_json TEXT,
    human_sightings_json TEXT,
    timestamp TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_detections_time ON detections(timestamp DESC);

CREATE TABLE IF NOT EXISTS detection_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL,
    elephant_detected INTEGER NOT NULL,
    movement TEXT NOT NULL,
    location TEXT NOT NULL,
    x_position REAL NOT NULL,
    y_position REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_det_hist_time ON detection_history(timestamp DESC);

CREATE TABLE IF NOT EXISTS human_sightings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL,
    sighting_id TEXT,
    x_position REAL NOT NULL,
    y_position REAL NOT NULL,
    location TEXT NOT NULL,
    confidence REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_human_time ON human_sightings(timestamp DESC);

CREATE TABLE IF NOT EXISTS alert_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL,
    time_str TEXT NOT NULL,
    mode TEXT NOT NULL,
    risk_score INTEGER NOT NULL,
    message TEXT NOT NULL,
    target_json TEXT
);
CREATE INDEX IF NOT EXISTS idx_alert_time ON alert_history(timestamp DESC);

CREATE TABLE IF NOT EXISTS nodes (
    node_id TEXT PRIMARY KEY,
    last_seen TEXT NOT NULL,
    power_source TEXT NOT NULL DEFAULT 'SOLAR',
    node_health TEXT NOT NULL DEFAULT 'UNKNOWN'
);

CREATE TABLE IF NOT EXISTS system_config (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""

def get_conn():
    conn = sqlite3.connect(str(DB_PATH), timeout=10, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn

@contextmanager
def db_cursor(commit=False):
    conn = get_conn()
    try:
        cur = conn.cursor()
        yield cur
        if commit:
            conn.commit()
    finally:
        conn.close()

def init_db():
    """Create DB file and all tables. Safe to call multiple times."""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = get_conn()
    try:
        conn.executescript(SCHEMA)
        conn.commit()
        # seed default config
        conn.execute("INSERT OR IGNORE INTO system_config(key, value) VALUES (?, ?)", ("camera_mode", "VIDEO"))
        conn.commit()
    finally:
        conn.close()
    print(f"[OK] Database ready: {DB_PATH} ({DB_PATH.stat().st_size} bytes)")

# ---------- Sensor ----------
def save_sensor_reading(record: dict, node_health: str, power_source: str):
    try:
        with db_cursor(commit=True) as cur:
            cur.execute("""
                INSERT INTO sensor_readings (node_id, motion, vibration, temperature, battery, buzzer, led, power_source, node_health, timestamp)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                record["node_id"], int(record["motion"]), int(record["vibration"]),
                float(record["temperature"]), int(record["battery"]),
                int(record["buzzer"]), int(record["led"]),
                power_source, node_health, record["timestamp"]
            ))
            # cap per node
            cur.execute("""
                DELETE FROM sensor_readings WHERE id IN (
                    SELECT id FROM sensor_readings WHERE node_id=? ORDER BY id DESC LIMIT -1 OFFSET ?
                )
            """, (record["node_id"], MAX_SENSOR_ROWS_PER_NODE))
            # upsert nodes table
            cur.execute("""
                INSERT INTO nodes(node_id, last_seen, power_source, node_health)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(node_id) DO UPDATE SET last_seen=excluded.last_seen, power_source=excluded.power_source, node_health=excluded.node_health
            """, (record["node_id"], record["timestamp"], power_source, node_health))
    except Exception as e:
        print(f"⚠️ DB save_sensor error: {e}")

def get_latest_sensor(node_id: str):
    try:
        with db_cursor() as cur:
            cur.execute("SELECT * FROM sensor_readings WHERE node_id=? ORDER BY id DESC LIMIT 1", (node_id,))
            row = cur.fetchone()
            return dict(row) if row else None
    except Exception:
        return None

# ---------- Detection ----------
def save_detection(record: dict):
    try:
        with db_cursor(commit=True) as cur:
            cur.execute("""
                INSERT INTO detections (elephant_detected, elephant_count, elephant_confidence, human_detected, human_count, vehicle_detected, vehicle_count, movement, location, x_position, y_position, primary_elephant_id, elephants_json, human_sightings_json, timestamp)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                int(record.get("elephant_detected", False)),
                int(record.get("elephant_count", 0)),
                float(record.get("elephant_confidence", 0)),
                int(record.get("human_detected", False)),
                int(record.get("human_count", 0)),
                int(record.get("vehicle_detected", False)),
                int(record.get("vehicle_count", 0)),
                str(record.get("movement", "NO MOVEMENT")),
                str(record.get("location", "NO ELEPHANT")),
                float(record.get("x_position", 0)),
                float(record.get("y_position", 0)),
                str(record.get("primary_elephant_id")) if record.get("primary_elephant_id") else None,
                json.dumps(record.get("elephants", [])),
                json.dumps(record.get("human_sightings", [])),
                str(record.get("timestamp"))
            ))
            # keep only last 500 detections to avoid bloat
            cur.execute("DELETE FROM detections WHERE id IN (SELECT id FROM detections ORDER BY id DESC LIMIT -1 OFFSET 500)")
    except Exception as e:
        print(f"⚠️ DB save_detection error: {e}")

def get_latest_detection():
    try:
        with db_cursor() as cur:
            cur.execute("SELECT * FROM detections ORDER BY id DESC LIMIT 1")
            row = cur.fetchone()
            if not row:
                return None
            d = dict(row)
            d["elephants"] = json.loads(d["elephants_json"] or "[]")
            d["human_sightings"] = json.loads(d["human_sightings_json"] or "[]")
            d["elephant_detected"] = bool(d["elephant_detected"])
            d["human_detected"] = bool(d["human_detected"])
            d["vehicle_detected"] = bool(d["vehicle_detected"])
            return d
    except Exception:
        return None

# ---------- Detection History ----------
def save_detection_history(entry: dict):
    try:
        with db_cursor(commit=True) as cur:
            cur.execute("""
                INSERT INTO detection_history (timestamp, elephant_detected, movement, location, x_position, y_position)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (entry["timestamp"], int(entry["elephant_detected"]), entry["movement"], entry["location"], float(entry["x_position"]), float(entry["y_position"])))
            cur.execute("DELETE FROM detection_history WHERE id IN (SELECT id FROM detection_history ORDER BY id DESC LIMIT -1 OFFSET ?)", (MAX_DETECTION_HISTORY,))
    except Exception as e:
        print(f"⚠️ DB save_detection_history error: {e}")

def load_detection_history(limit=50):
    try:
        with db_cursor() as cur:
            cur.execute("SELECT timestamp, elephant_detected, movement, location, x_position, y_position FROM detection_history ORDER BY id DESC LIMIT ?", (limit,))
            rows = cur.fetchall()
            return [dict(r) | {"elephant_detected": bool(r["elephant_detected"])} for r in reversed(rows)]
    except Exception:
        return []

# ---------- Human Sightings ----------
def save_human_sighting(entry: dict):
    try:
        with db_cursor(commit=True) as cur:
            cur.execute("""
                INSERT INTO human_sightings (timestamp, sighting_id, x_position, y_position, location, confidence)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (entry["timestamp"], str(entry.get("id")), float(entry["x_position"]), float(entry["y_position"]), str(entry["location"]), float(entry["confidence"])))
            cur.execute("DELETE FROM human_sightings WHERE id IN (SELECT id FROM human_sightings ORDER BY id DESC LIMIT -1 OFFSET ?)", (MAX_HUMAN_HISTORY,))
    except Exception as e:
        print(f"⚠️ DB save_human_sighting error: {e}")

def load_human_sightings(limit=50):
    try:
        with db_cursor() as cur:
            cur.execute("SELECT timestamp, sighting_id as id, x_position, y_position, location, confidence FROM human_sightings ORDER BY id DESC LIMIT ?", (limit,))
            rows = cur.fetchall()
            return [dict(r) for r in reversed(rows)]
    except Exception:
        return []

# ---------- Alert History ----------
def save_alert(entry: dict):
    try:
        with db_cursor(commit=True) as cur:
            cur.execute("""
                INSERT INTO alert_history (timestamp, time_str, mode, risk_score, message, target_json)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (entry["timestamp"], entry["time"], entry["mode"], int(entry["risk_score"]), entry["message"], json.dumps(entry.get("target", []))))
            cur.execute("DELETE FROM alert_history WHERE id IN (SELECT id FROM alert_history ORDER BY id DESC LIMIT -1 OFFSET ?)", (MAX_ALERT_HISTORY,))
    except Exception as e:
        print(f"⚠️ DB save_alert error: {e}")

def load_alerts(limit=20):
    try:
        with db_cursor() as cur:
            cur.execute("SELECT timestamp, time_str as time, mode, risk_score, message, target_json FROM alert_history ORDER BY id DESC LIMIT ?", (limit,))
            rows = cur.fetchall()
            out = []
            for r in reversed(rows):
                d = dict(r)
                d["target"] = json.loads(d["target_json"] or "[]")
                del d["target_json"]
                out.append(d)
            return out
    except Exception:
        return []

def count_alerts():
    try:
        with db_cursor() as cur:
            cur.execute("SELECT COUNT(*) as c FROM alert_history")
            return cur.fetchone()["c"]
    except Exception:
        return 0

# ---------- Config ----------
def set_config(key: str, value: str):
    try:
        with db_cursor(commit=True) as cur:
            cur.execute("INSERT INTO system_config(key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, value))
    except Exception as e:
        print(f"⚠️ DB set_config error: {e}")

def get_config(key: str, default=None):
    try:
        with db_cursor() as cur:
            cur.execute("SELECT value FROM system_config WHERE key=?", (key,))
            row = cur.fetchone()
            return row["value"] if row else default
    except Exception:
        return default

if __name__ == "__main__":
    init_db()
    print("Tables created. You can inspect with: sqlite3 eleguard.db '.tables'")
