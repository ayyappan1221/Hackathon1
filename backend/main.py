from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from pathlib import Path
from datetime import datetime
import base64
import asyncio
import smtplib
import json
import math
import os
import threading
import time
from email.mime.text import MIMEText

# ---- SQLite persistence (graceful fallback if file missing) ----
try:
    from database import (
        init_db, save_sensor_reading, save_detection, save_detection_history,
        save_human_sighting, save_alert, set_config, get_config,
        load_detection_history, load_human_sightings, load_alerts
    )
    DB_AVAILABLE = True
except ImportError:
    # fallback when running as `uvicorn main:app` vs `uvicorn backend.main:app`
    try:
        from backend.database import (
            init_db, save_sensor_reading, save_detection, save_detection_history,
            save_human_sighting, save_alert, set_config, get_config,
            load_detection_history, load_human_sightings, load_alerts
        )
        DB_AVAILABLE = True
    except Exception as _e:
        print(f"⚠️ Database module not available: {_e} - running in-memory only")
        DB_AVAILABLE = False
        def init_db(): pass
        def save_sensor_reading(*a, **kw): pass
        def save_detection(*a, **kw): pass
        def save_detection_history(*a, **kw): pass
        def save_human_sighting(*a, **kw): pass
        def save_alert(*a, **kw): pass
        def set_config(*a, **kw): pass
        def get_config(k, d=None): return d
        def load_detection_history(*a, **kw): return []
        def load_human_sightings(*a, **kw): return []
        def load_alerts(*a, **kw): return []


# =========================================================
# ELEGUARD AI - FASTAPI BACKEND (FULL FEATURE VERSION)
# =========================================================

app = FastAPI(
    title="EleGuard AI Backend",
    version="2.0.0"
)

# Render injects PORT env var - keep for local too
PORT = int(os.getenv("PORT", "8000"))

# CORS: allow Render frontend via env, plus local vite
_allowed_origins = os.getenv("ALLOWED_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173").split(",")
_allowed_origins = [o.strip() for o in _allowed_origins if o.strip()]
# also allow any *.onrender.com and *.vercel.app for demo
# FastAPI CORSMiddleware doesn't support wildcards, so we allow all if env says "*"
_allow_credentials = True
if os.getenv("CORS_ALLOW_ALL", "false").lower() == "true":
    _allowed_origins = ["*"]
    _allow_credentials = False

app.add_middleware(
    CORSMiddleware,
    allow_origins=_allowed_origins,
    allow_credentials=_allow_credentials,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Init DB on import (creates eleguard.db if missing) + hydrate in-memory caches
try:
    init_db()
except Exception as _db_err:
    print(f"⚠️ DB init failed: {_db_err}")

@app.on_event("startup")
async def _hydrate_from_db():
    """Restore last state from SQLite so restart doesn't wipe history."""
    if not DB_AVAILABLE:
        return
    try:
        # hydrate histories for heatmap/prediction continuity
        from database import get_latest_detection as _get_latest_det
    except ImportError:
        try:
            from backend.database import get_latest_detection as _get_latest_det
        except Exception:
            _get_latest_det = lambda: None
    try:
        hist = load_detection_history(limit=MAX_DETECTION_HISTORY)
        if hist:
            detection_history.extend(hist)
            global last_logged_detection
            last_logged_detection = hist[-1] if hist else None
        h_hist = load_human_sightings(limit=MAX_HUMAN_HISTORY)
        if h_hist:
            human_sighting_history.extend(h_hist)
        a_hist = load_alerts(limit=MAX_ALERT_HISTORY)
        if a_hist:
            alert_history.extend(a_hist)
            if a_hist:
                last = a_hist[-1]
                global last_alert_state, last_alert_log_time
                last_alert_state = last.get("mode")
                try:
                    last_alert_log_time = datetime.fromisoformat(last.get("timestamp"))
                except Exception:
                    pass
        # restore camera mode
        global camera_mode
        saved_mode = get_config("camera_mode", None)
        if saved_mode in ("VIDEO", "CAMERA"):
            camera_mode = saved_mode
        # restore latest detection if present
        latest = _get_latest_det()
        if latest and latest.get("timestamp"):
            global latest_detection_data
            latest_detection_data = latest
    except Exception as _e:
        print(f"⚠️ DB hydrate failed: {_e}")

@app.on_event("startup")
async def _start_demo_simulator():
    """Start the demo simulator background thread if demo mode is enabled."""
    if demo_mode_enabled:
        t = threading.Thread(target=_demo_simulator_loop, daemon=True)
        t.start()
        print("🎬 Demo simulator started (DEMO_MODE=true)")


# =========================================================
# ONE-CLICK RAILWAY: Serve Vite frontend from FastAPI when built
# =========================================================

# =========================================================
# DEMO MODE SIMULATOR
# =========================================================
# When enabled, the backend auto-simulates elephant movement,
# sensor data, and video frames so the dashboard works on Render
# without the local AI script running.

demo_mode_enabled = os.getenv("DEMO_MODE", "true").lower() == "true"
_demo_lock = threading.Lock()
_demo_elephant_x = 0.1
_demo_phase = 0  # 0=forest, 1=moving, 2=approaching, 3=near village, 4=moving away
_demo_start_time = None


@app.post("/api/demo/toggle")
def toggle_demo_mode(data: dict = None):
    global demo_mode_enabled
    with _demo_lock:
        demo_mode_enabled = not demo_mode_enabled
        state = "enabled" if demo_mode_enabled else "disabled"
    return {"demo_mode": demo_mode_enabled, "message": f"Demo mode {state}"}


@app.get("/api/demo/status")
def get_demo_status():
    return {"demo_mode": demo_mode_enabled}


def _generate_demo_frame(x_pos, risk_level, elephant_count=1):
    """Generate a synthetic JPEG frame using Pillow."""
    try:
        from PIL import Image, ImageDraw, ImageFont
    except ImportError:
        return None

    W, H = 640, 480
    img = Image.new("RGB", (W, H), (34, 80, 34))  # dark forest green
    draw = ImageDraw.Draw(img)

    # forest gradient background
    for y in range(H):
        r = int(34 + (y / H) * 20)
        g = int(80 - (y / H) * 30)
        b = int(34 + (y / H) * 10)
        draw.line([(0, y), (W, y)], fill=(r, g, b))

    # tree silhouettes
    import random
    rng = random.Random(42)
    for _ in range(8):
        tx = rng.randint(0, W)
        th = rng.randint(80, 180)
        tw = rng.randint(20, 40)
        ty = H - th
        draw.polygon([(tx, ty), (tx - tw, H), (tx + tw, H)], fill=(20, 50, 20))

    # village zone (right side)
    vx = int(VILLAGE_LIMIT * W)
    draw.rectangle([vx, H - 60, W, H], fill=(120, 100, 60))
    draw.text((vx + 10, H - 50), "VILLAGE", fill=(200, 180, 100))

    # elephant silhouette (simple oval + trunk)
    ex = int(x_pos * W)
    ey = H - 120
    ew, eh = 80, 50
    draw.ellipse([ex - ew // 2, ey, ex + ew // 2, ey + eh], fill=(100, 100, 100))
    draw.ellipse([ex + ew // 2 - 10, ey + 5, ex + ew // 2 + 15, ey + eh - 5], fill=(100, 100, 100))
    # trunk
    draw.line([(ex + ew // 2 + 5, ey + 15), (ex + ew // 2 + 25, ey + 35)], fill=(100, 100, 100), width=4)
    # legs
    for lx in [ex - 20, ex - 5, ex + 10, ex + 25]:
        draw.rectangle([lx, ey + eh, lx + 6, ey + eh + 20], fill=(80, 80, 80))

    # bounding box
    color = {"CRITICAL": (255, 0, 0), "HIGH": (255, 165, 0), "MEDIUM": (255, 255, 0), "LOW": (0, 255, 0)}.get(risk_level, (0, 255, 0))
    draw.rectangle([ex - ew // 2 - 5, ey - 5, ex + ew // 2 + 30, ey + eh + 25], outline=color, width=2)
    draw.text((ex - ew // 2 - 5, ey - 20), f"Elephant ({risk_level})", fill=color)

    # overlay info
    draw.rectangle([0, 0, 220, 60], fill=(0, 0, 0, 180))
    draw.text((10, 5), "EleGuard AI - DEMO", fill=(0, 255, 0))
    draw.text((10, 25), f"Risk: {risk_level} | Elephants: {elephant_count}", fill=(255, 255, 255))

    import io
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=75)
    return buf.getvalue()


def _demo_simulator_loop():
    """Background thread that simulates elephant movement + sensor data."""
    global _demo_elephant_x, _demo_phase, _demo_start_time
    global latest_detection_data, latest_sensor_data, latest_video_frame

    _demo_start_time = time.time()

    # Phase durations (seconds): forest → moving → approaching → near → moving away → cycle
    phase_durations = [8, 6, 6, 5, 6]  # total ~31s per cycle
    phase_movements = ["IN FOREST", "MOVING", "APPROACHING VILLAGE", "NEAR VILLAGE", "MOVING AWAY"]
    phase_x_targets = [0.25, 0.40, 0.60, 0.80, 0.30]  # target x for each phase

    while True:
        time.sleep(1.0)  # update every 1s

        if not demo_mode_enabled:
            continue

        elapsed = time.time() - _demo_start_time
        cycle_pos = elapsed % sum(phase_durations)

        # determine current phase
        cumulative = 0
        for i, dur in enumerate(phase_durations):
            if cycle_pos < cumulative + dur:
                _demo_phase = i
                break
            cumulative += dur

        # interpolate x position within phase
        phase_elapsed = cycle_pos - cumulative
        phase_progress = min(phase_elapsed / phase_durations[_demo_phase], 1.0)

        target_x = phase_x_targets[_demo_phase]
        start_x = phase_x_targets[(_demo_phase - 1) % len(phase_durations)] if _demo_phase > 0 else phase_x_targets[-1]
        _demo_elephant_x = start_x + (target_x - start_x) * phase_progress
        _demo_elephant_x = max(0.05, min(0.95, _demo_elephant_x))

        movement = phase_movements[_demo_phase]
        location = get_zone_label(_demo_elephant_x)
        risk_data = {"movement": movement}
        # quick risk calc for frame color
        rm = movement
        if rm == "IN FOREST": rl = "MEDIUM"
        elif rm == "MOVING": rl = "MEDIUM"
        elif rm == "APPROACHING VILLAGE": rl = "HIGH"
        elif rm == "NEAR VILLAGE": rl = "CRITICAL"
        elif rm == "MOVING AWAY": rl = "MEDIUM"
        else: rl = "MEDIUM"

        # update detection data
        now_iso = datetime.now().isoformat()
        latest_detection_data = {
            "elephant_detected": True,
            "elephant_count": 1,
            "elephant_confidence": round(0.75 + 0.2 * math.sin(elapsed * 0.3), 2),
            "human_detected": False,
            "human_count": 0,
            "vehicle_detected": False,
            "vehicle_count": 0,
            "movement": movement,
            "location": location,
            "x_position": round(_demo_elephant_x, 3),
            "y_position": round(0.5 + 0.1 * math.sin(elapsed * 0.2), 3),
            "primary_elephant_id": "DEMO_001",
            "elephants": [{
                "id": "DEMO_001",
                "confidence": round(0.75 + 0.2 * math.sin(elapsed * 0.3), 2),
                "x_position": round(_demo_elephant_x, 3),
                "y_position": round(0.5 + 0.1 * math.sin(elapsed * 0.2), 3),
                "movement": movement,
                "location": location
            }],
            "human_sightings": [],
            "timestamp": now_iso
        }

        # update sensor data (simulate vibration when elephant moves)
        vibration_base = 20 if movement in ("MOVING", "APPROACHING VILLAGE", "NEAR VILLAGE") else 5
        latest_sensor_data = {
            "node_id": "NODE_01",
            "motion": movement not in ("IN FOREST", "NO MOVEMENT"),
            "vibration": int(vibration_base + 10 * abs(math.sin(elapsed * 0.5))),
            "temperature": round(28.0 + 3 * math.sin(elapsed * 0.1), 1),
            "battery": max(20, int(95 - elapsed * 0.01)),
            "buzzer": rl == "CRITICAL",
            "led": rl in ("CRITICAL", "HIGH"),
            "timestamp": now_iso
        }

        # generate video frame
        frame = _generate_demo_frame(_demo_elephant_x, rl)
        if frame:
            latest_video_frame = frame
_frontend_candidates = [
    Path(__file__).parent.parent / "frontend" / "dist",  # /app/frontend/dist (Dockerfile)
    Path(__file__).parent / ".." / "frontend" / "dist",  # alt
    Path("frontend/dist"),                                 # CWD fallback
    Path("/app/frontend/dist"),
]
_frontend_dist = next((p.resolve() for p in _frontend_candidates if p.exists() and (p / "index.html").exists()), None)
if _frontend_dist:
    print(f"✅ Serving frontend from {_frontend_dist}")
    # API routes already registered; mount static last so /api/* takes precedence
    app.mount("/assets", StaticFiles(directory=str(_frontend_dist / "assets")), name="assets")
    @app.get("/{full_path:path}")
    async def _serve_frontend(full_path: str):
        # Don't hijack API/docs
        if full_path.startswith("api/") or full_path in ("docs", "openapi.json", "redoc"):
            from fastapi.responses import JSONResponse
            return JSONResponse({"detail": "Not Found"}, status_code=404)
        target = _frontend_dist / full_path
        if full_path and target.exists() and target.is_file():
            return FileResponse(str(target))
        return FileResponse(str(_frontend_dist / "index.html"))
else:
    print("ℹ️ Frontend dist not found - API-only mode (dev)")

# =========================================================
# CORS
# =========================================================

# =========================================================
# CONFIG
# =========================================================

DEFAULT_NODE_ID = "NODE_01"

# =========================================================
# INPUT SOURCE MODE (VIDEO / LAPTOP CAMERA)
# =========================================================
# VIDEO is the existing demo mode. CAMERA switches the AI script
# to the laptop webcam without changing the rest of the pipeline.
camera_mode = "VIDEO"


# =========================================================
# EMAIL ALERT CONFIG (Gmail SMTP) - feature: real alert on CRITICAL risk
# =========================================================
#
# Switched from Twilio WhatsApp/SMS to email because Twilio trial
# accounts block all free-text messages (SMS + WhatsApp) behind a
# paid-upgrade wall as of 2026 - templates only, no way around it
# without a credit card. Email has no such restriction and is 100%
# free and unlimited.
#
# SETUP:
# 1. myaccount.google.com -> Security -> 2-Step Verification (turn ON)
# 2. Security -> App passwords -> generate one named "EleGuard"
# 3. Copy the 16-character password (no spaces) into EMAIL_APP_PASSWORD
# 4. Set EMAIL_SENDER to that same Gmail address
# 5. Set EMAIL_RECIPIENT to wherever the alert should land
#
# If left disabled, the app runs completely normally - email sending
# is just silently skipped.
# =========================================================

EMAIL_ENABLED = os.getenv("EMAIL_ENABLED", "true").lower() == "true"
EMAIL_SENDER = os.getenv("EMAIL_SENDER", "dharshinia.2025ibm@gmail.com")
EMAIL_APP_PASSWORD = os.getenv("EMAIL_APP_PASSWORD", "udvezmrpgbbvxazf")
EMAIL_RECIPIENT = os.getenv("EMAIL_RECIPIENT", "dharshinia.2025ibm@gmail.com")
EMAIL_SMTP_HOST = os.getenv("EMAIL_SMTP_HOST", "smtp.gmail.com")
EMAIL_SMTP_PORT = int(os.getenv("EMAIL_SMTP_PORT", "587"))

# Minimum seconds between alert emails - protects against every single
# CRITICAL poll spamming the inbox.
SMS_COOLDOWN_SECONDS = 60

# If a node hasn't posted sensor data in this many seconds,
# we treat it as OFFLINE / failed (sensor failure detection).
SENSOR_STALE_SECONDS = 8

# Zone thresholds - kept identical to the AI script so
# predictions/labels line up with what YOLO reports.
FOREST_LIMIT = 0.45
VILLAGE_LIMIT = 0.72

# =========================================================
# NEW (STEP 1): DETECTION-HISTORY DEDUP THRESHOLDS
# =========================================================
#
# The AI script can post the same movement/location several times a
# second (frame-to-frame). Logging every single POST to
# detection_history produced duplicate rows like:
#   4:06:46  MOVING AWAY
#   4:06:46  MOVING AWAY
#   4:06:46  MOVING AWAY
#
# We now only log a new history row when something meaningful
# happened: the elephant/movement/location state changed, OR the
# elephant actually moved a noticeable amount, OR a "heartbeat"
# interval has passed (so the heatmap / movement-speed prediction
# still get a steady trickle of samples even while the elephant sits
# still in one spot).
# =========================================================

DETECTION_LOG_POSITION_DELTA = 0.02     # log if x/y shifted at least this much (0-1 normalized)
DETECTION_LOG_HEARTBEAT_SECONDS = 3     # otherwise log at most once every N seconds
DETECTION_LOG_MIN_INTERVAL_SECONDS = 1.5
# =========================================================
# NEW (STEP 2): ALERT-HISTORY ANTI-FLAP COOLDOWN
# =========================================================
#
# Risk mode can flicker frame-to-frame (WARNING <-> MONITOR) when the
# AI's movement label bounces around a threshold. Logging every flip
# spammed Alert History. Now, when the mode changes to something
# *less* urgent (or sideways), we wait at least this many seconds
# since the last logged event before logging the new one. Escalating
# straight into CRITICAL always logs immediately - safety first.
# =========================================================

ALERT_MODE_COOLDOWN_SECONDS = 8
CRITICAL_REALERT_COOLDOWN_SECONDS = 5


# =========================================================
# LATEST IoT SENSOR DATA (single-node, kept for backward compat)
# =========================================================

latest_sensor_data = {
    "node_id": DEFAULT_NODE_ID,
    "motion": False,
    "vibration": 0,
    "temperature": 0,
    "battery": 100,
    "buzzer": False,
    "led": False,
    "timestamp": None
}

# Multiple IoT nodes support: node_id -> sensor dict
# (feature 35 - Multiple IoT nodes)
nodes_data = {}
nodes_last_seen = {}          # node_id -> datetime, for failure detection
nodes_power_source = {}       # node_id -> "SOLAR" | "GRID" (concept only)


# =========================================================
# LATEST AI DETECTION DATA
# =========================================================

latest_detection_data = {
    "elephant_detected": False,
    "elephant_count": 0,
    "elephant_confidence": 0,
    "human_detected": False,
    "human_count": 0,
    "vehicle_detected": False,
    "vehicle_count": 0,
    "movement": "NO MOVEMENT",
    "location": "NO ELEPHANT",
    "x_position": 0,
    "y_position": 0,
    "primary_elephant_id": None,
    "elephants": [],
    "human_sightings": [],
    "timestamp": None
}

# Detection history (feature 27 - Detection history / used for
# heatmap + movement prediction). Bounded so memory stays flat.
detection_history = []
MAX_DETECTION_HISTORY = 300

# Separate human sighting history for dashboard analytics.
human_sighting_history = []
MAX_HUMAN_HISTORY = 200

# NEW (STEP 1): tracks the last row actually written to
# detection_history, so we can compare against it for dedup.
last_logged_detection = None


# =========================================================
# HUMAN SIGHTING HISTORY
# =========================================================

@app.get("/api/humans/history")
def get_human_history():
    return {
        "total_sightings": len(human_sighting_history),
        "current_count": int(latest_detection_data.get("human_count", 0)),
        "events": human_sighting_history[-50:]
    }


# =========================================================
# ALERT HISTORY  (feature 23/25/26 - automatic + officer/village alerts)
# =========================================================

alert_history = []
MAX_ALERT_HISTORY = 200

last_alert_state = None
last_alert_log_time = None
last_critical_log_time = None
critical_alert_active = False

# False alarm tracking (feature 31)
false_alarm_count = 0


# =========================================================
# HOME
# =========================================================

@app.get("/")
def home():
    return {
        "project": "EleGuard AI",
        "status": "Backend Online",
        "version": "2.0.0"
    }


# =========================================================
# HELPERS - ZONE LABEL (shared by prediction + safe route)
# =========================================================

def get_zone_label(x_position):
    if x_position < FOREST_LIMIT:
        return "IN FOREST"
    elif x_position < VILLAGE_LIMIT:
        return "APPROACHING VILLAGE"
    else:
        return "NEAR VILLAGE"


# =========================================================
# POST SENSOR DATA
# =========================================================

@app.post("/api/sensors")
def receive_sensor_data(data: dict):

    global latest_sensor_data

    node_id = str(data.get("node_id", DEFAULT_NODE_ID))

    sensor_record = {
        "node_id": node_id,
        "motion": bool(data.get("motion", False)),
        "vibration": max(0, min(100, int(data.get("vibration", 0)))),
        "temperature": round(float(data.get("temperature", 0)), 1),
        "battery": max(0, min(100, int(data.get("battery", 100)))),
        "buzzer": bool(data.get("buzzer", False)),
        "led": bool(data.get("led", False)),
        "timestamp": datetime.now().isoformat()
    }

    # Keep single-node contract stable for the existing dashboard
    if node_id == DEFAULT_NODE_ID:
        latest_sensor_data = sensor_record

    # Multi-node storage (feature 35)
    nodes_data[node_id] = sensor_record
    nodes_last_seen[node_id] = datetime.now()
    nodes_power_source.setdefault(node_id, "SOLAR")

    # ---- persist to SQLite ----
    try:
        health = get_node_health(node_id)
        save_sensor_reading(sensor_record, health, nodes_power_source.get(node_id, "SOLAR"))
    except Exception as _e:
        print(f"⚠️ save_sensor DB error: {_e}")

    return {
        "message": "Sensor data received",
        "data": sensor_record
    }


# =========================================================
# GET SENSOR DATA (single node - backward compatible)
# =========================================================

@app.get("/api/sensors")
def get_sensor_data():

    health = get_node_health(DEFAULT_NODE_ID)

    return {
        **latest_sensor_data,
        "node_health": health,
        "power_source": nodes_power_source.get(DEFAULT_NODE_ID, "SOLAR")
    }


# =========================================================
# GET ALL NODES (feature 15/35 - node health + multiple nodes)
# =========================================================

def get_node_health(node_id):
    last_seen = nodes_last_seen.get(node_id)

    if last_seen is None:
        return "UNKNOWN"

    age = (datetime.now() - last_seen).total_seconds()

    return "ONLINE" if age <= SENSOR_STALE_SECONDS else "OFFLINE"


@app.get("/api/nodes")
def get_all_nodes():

    result = []

    for node_id, sensor in nodes_data.items():
        result.append({
            **sensor,
            "node_health": get_node_health(node_id),
            "power_source": nodes_power_source.get(node_id, "SOLAR")
        })

    return {
        "total_nodes": len(result),
        "nodes": result
    }


# =========================================================
# POST AI DETECTION DATA
# =========================================================

@app.post("/api/detection")
def receive_detection_data(data: dict):

    global latest_detection_data, last_logged_detection

    latest_detection_data = data.copy()

    latest_detection_data.setdefault("elephant_detected", False)
    latest_detection_data.setdefault("elephant_count", 0)
    latest_detection_data.setdefault("elephant_confidence", 0)
    latest_detection_data.setdefault("human_detected", False)
    latest_detection_data.setdefault("human_count", 0)
    latest_detection_data.setdefault("vehicle_detected", False)
    latest_detection_data.setdefault("vehicle_count", 0)
    latest_detection_data.setdefault("location", "NO ELEPHANT")
    latest_detection_data.setdefault("movement", "NO MOVEMENT")
    latest_detection_data.setdefault("x_position", 0)
    latest_detection_data.setdefault("y_position", 0)
    latest_detection_data.setdefault("elephants", [])
    latest_detection_data.setdefault("human_sightings", [])

    latest_detection_data["timestamp"] = datetime.now().isoformat()

    # =====================================================
    # STEP 1 FIX: log to history (feature 27) ONLY when
    # something meaningful happened - state changed, the
    # elephant actually moved, or a heartbeat interval passed.
    # This removes the "same second, same label x3" duplicates
    # while still feeding the heatmap / speed prediction.
    # =====================================================

    should_log_detection = False

    if last_logged_detection is None:
        should_log_detection = True
    else:
        seconds_since_last_log = (
            datetime.now() - datetime.fromisoformat(last_logged_detection["timestamp"])
        ).total_seconds()

        if seconds_since_last_log < DETECTION_LOG_MIN_INTERVAL_SECONDS:
            should_log_detection = False
        else:
            state_changed = (
                latest_detection_data["elephant_detected"] != last_logged_detection["elephant_detected"]
                or latest_detection_data["movement"] != last_logged_detection["movement"]
                or latest_detection_data["location"] != last_logged_detection["location"]
            )

            moved_enough = (
                abs(latest_detection_data["x_position"] - last_logged_detection["x_position"]) >= DETECTION_LOG_POSITION_DELTA
                or abs(latest_detection_data["y_position"] - last_logged_detection["y_position"]) >= DETECTION_LOG_POSITION_DELTA
            )

            should_log_detection = (
                state_changed
                or moved_enough
                or seconds_since_last_log >= DETECTION_LOG_HEARTBEAT_SECONDS
            )

    # =====================================================
    # HUMAN SIGHTING HISTORY (separate from elephant history)
    # =====================================================
    human_sightings = latest_detection_data.get("human_sightings", [])
    if isinstance(human_sightings, list):
        for sighting in human_sightings:
            if not isinstance(sighting, dict):
                continue
            h_entry = {
                "timestamp": latest_detection_data["timestamp"],
                "id": sighting.get("id"),
                "x_position": float(sighting.get("x_position", 0)),
                "y_position": float(sighting.get("y_position", 0)),
                "location": str(sighting.get("location", "UNKNOWN")).upper(),
                "confidence": round(float(sighting.get("confidence", 0)), 2),
            }
            human_sighting_history.append(h_entry)
            try:
                save_human_sighting(h_entry)
            except Exception as _e:
                print(f"⚠️ save_human DB error: {_e}")
    if len(human_sighting_history) > MAX_HUMAN_HISTORY:
        del human_sighting_history[:-MAX_HUMAN_HISTORY]

    if should_log_detection:
        history_entry = {
            "timestamp": latest_detection_data["timestamp"],
            "elephant_detected": latest_detection_data["elephant_detected"],
            "movement": latest_detection_data["movement"],
            "location": latest_detection_data["location"],
            "x_position": latest_detection_data["x_position"],
            "y_position": latest_detection_data["y_position"],
        }

        detection_history.append(history_entry)
        last_logged_detection = history_entry

        if len(detection_history) > MAX_DETECTION_HISTORY:
            del detection_history[0]
        try:
            save_detection_history(history_entry)
        except Exception as _e:
            print(f"⚠️ save_det_hist DB error: {_e}")

    # ---- persist latest detection snapshot ----
    try:
        save_detection(latest_detection_data)
    except Exception as _e:
        print(f"⚠️ save_detection DB error: {_e}")

    return {
        "message": "AI detection received",
        "data": latest_detection_data
    }


# =========================================================
# GET / SET INPUT SOURCE MODE
# =========================================================
# The React dashboard uses these endpoints to switch the existing
# AI loop between the demo video and the laptop webcam.

@app.get("/api/camera/mode")
def get_camera_mode():
    return {
        "mode": camera_mode,
        "camera_enabled": camera_mode == "CAMERA"
    }


@app.post("/api/camera/mode")
def set_camera_mode(data: dict):
    global camera_mode

    requested_mode = str(data.get("mode", "VIDEO")).upper().strip()

    if requested_mode not in {"VIDEO", "CAMERA"}:
        requested_mode = "VIDEO"

    camera_mode = requested_mode
    try:
        set_config("camera_mode", camera_mode)
    except Exception as _e:
        print(f"⚠️ set_config DB error: {_e}")

    return {
        "message": "Input source updated",
        "mode": camera_mode,
        "camera_enabled": camera_mode == "CAMERA"
    }


# =========================================================
# GET AI DETECTION DATA
# =========================================================

@app.get("/api/detection")
def get_detection_data():
    return latest_detection_data


# =========================================================
# LIVE VIDEO FEED (annotated YOLO frames -> MJPEG stream)
# =========================================================
#
# The AI script (detect_and_send.py) draws bounding boxes on
# each processed frame and POSTs the JPEG here. We keep only the
# latest frame in memory and continuously re-serve it as an MJPEG
# stream, so the dashboard <img> tag shows the live detection
# video WITHOUT needing a desktop cv2.imshow() window (which
# judges can't see on a shared screen/projector).
# =========================================================

latest_video_frame = None


@app.post("/api/video-frame")
def receive_video_frame(data: dict):

    global latest_video_frame

    frame_b64 = data.get("frame")

    if frame_b64:
        try:
            latest_video_frame = base64.b64decode(frame_b64)
        except Exception:
            pass

    return {"message": "frame received"}


async def mjpeg_generator():
    while True:
        if latest_video_frame is not None:
            yield (
                b"--frame\r\n"
                b"Content-Type: image/jpeg\r\n\r\n"
                + latest_video_frame
                + b"\r\n"
            )
        await asyncio.sleep(0.08)  # ~12 fps re-serve rate


@app.get("/api/video-feed")
def video_feed():
    return StreamingResponse(
        mjpeg_generator(),
        media_type="multipart/x-mixed-replace; boundary=frame"
    )


@app.get("/api/video-frame")
def video_frame_single():
    if latest_video_frame is None:
        from fastapi.responses import Response
        return Response(content=b"", media_type="image/jpeg", status_code=204)
    from fastapi.responses import Response
    return Response(content=latest_video_frame, media_type="image/jpeg")


# =========================================================
# MOVEMENT PREDICTION  (feature 7 - Movement prediction)
# =========================================================

def predict_movement():

    # IMPORTANT FIX:
    # Direction is taken from the CURRENT "movement" field (the same
    # value already shown elsewhere on the dashboard) instead of being
    # re-derived independently from a 5-sample window. Re-deriving it
    # separately could disagree with "movement" (e.g. card says MOVING
    # toward the village while prediction said "heading away") whenever
    # the recent window had mixed directions. History is still used,
    # but only to measure SPEED, never to flip the direction.

    elephant_detected = bool(latest_detection_data.get("elephant_detected", False))
    movement = str(latest_detection_data.get("movement", "")).upper().strip()

    points = [
        d for d in detection_history
        if d.get("elephant_detected")
    ]

    if not elephant_detected:
        return {
            "trend": "NO_ELEPHANT",
            "predicted_zone_30s": "NO ELEPHANT",
            "eta_to_village_seconds": None
        }

    if not points:
        return {
            "trend": "INSUFFICIENT_DATA",
            "predicted_zone_30s": get_zone_label(
                latest_detection_data.get("x_position", 0)
            ),
            "eta_to_village_seconds": None
        }

    current_x = points[-1]["x_position"]

    if movement in ("MOVING", "APPROACHING VILLAGE", "NEAR VILLAGE"):
        trend, direction = "TOWARD_VILLAGE", 1
    elif movement == "MOVING AWAY":
        trend, direction = "MOVING_AWAY", -1
    else:
        trend, direction = "STATIONARY", 0

    if len(points) < 2:
        return {
            "trend": "INSUFFICIENT_DATA",
            "predicted_zone_30s": get_zone_label(current_x),
            "eta_to_village_seconds": None
        }

    if direction == 0:
        return {
            "trend": trend,
            "predicted_zone_30s": get_zone_label(current_x),
            "eta_to_village_seconds": None
        }

    # Speed magnitude only (direction already fixed above)
    recent = points[-5:]
    t0 = datetime.fromisoformat(recent[0]["timestamp"])
    t1 = datetime.fromisoformat(recent[-1]["timestamp"])
    dt = (t1 - t0).total_seconds()
    speed = (abs(recent[-1]["x_position"] - recent[0]["x_position"]) / dt) if dt > 0 else 0

    future_x = max(0.0, min(1.0, current_x + direction * speed * 30))

    eta = None
    if direction == 1 and speed > 0:
        remaining = max(0.0, 1.0 - current_x)
        eta = round(remaining / speed, 1)

    return {
        "trend": trend,
        "predicted_zone_30s": get_zone_label(future_x),
        "eta_to_village_seconds": eta
    }


# =========================================================
# SAFE ROUTE RECOMMENDATION (feature 22)
# =========================================================

def get_safe_route(risk_level):

    routes = {
        "CRITICAL": "🚨 Evacuate via South Road immediately. Avoid the North forest path.",
        "HIGH": "⚠️ Use the East bypass route. Avoid the direct forest trail.",
        "MEDIUM": "🟡 Proceed with caution on the main road. Stay alert near the forest edge.",
        "LOW": "✅ All routes are currently safe. No restrictions."
    }

    return routes.get(risk_level, routes["LOW"])


# =========================================================
# VOICE ALERT TEXT - Tamil + English (feature 24)
# =========================================================

def get_voice_alert(risk_level, location):

    if risk_level == "CRITICAL":
        return (
            "எச்சரிக்கை! யானை கிராமத்திற்கு அருகில் உள்ளது. "
            "Warning! Elephant is near the village. Take immediate precaution."
        )

    if risk_level == "HIGH":
        return (
            "எச்சரிக்கை! யானை நகர்ந்து கொண்டிருக்கிறது. "
            "Warning! The elephant is moving. Stay alert."
        )

    return None


# =========================================================
# EXPLAINABLE AI (feature 9)
# =========================================================

def build_explanation(elephant_detected, movement, location, risk_level, elephant_count=1):

    if not elephant_detected:
        return "No elephant is currently detected, so risk is LOW by default."

    base = (
        f"Risk is {risk_level} because the elephant's movement is "
        f"classified as '{movement}' while located '{location}'."
    )

    if elephant_count > 1:
        base += f" (Based on the most at-risk of {elephant_count} elephants currently detected.)"

    return base


# =========================================================
# ALERT TARGETS - forest officer / village (feature 25/26)
# =========================================================

def get_alert_targets(risk_level):

    if risk_level == "CRITICAL":
        return ["FOREST_OFFICER", "VILLAGE"]

    if risk_level == "HIGH":
        return ["FOREST_OFFICER"]

    return []


# =========================================================
# REAL EMAIL ALERT (Gmail SMTP) - feature: judges get an actual alert
# =========================================================

last_sms_time = None
last_sms_status = "DISABLED"  # DISABLED | SENT | FAILED | SKIPPED_COOLDOWN


def send_sms_alert(message):
    """Sends a real email alert. Kept the name send_sms_alert so the rest
    of the app (log_alert_if_needed) doesn't need to change."""

    global last_sms_time, last_sms_status

    if not EMAIL_ENABLED:
        last_sms_status = "DISABLED"
        return False

    now = datetime.now()

    if last_sms_time is not None and (now - last_sms_time).total_seconds() < SMS_COOLDOWN_SECONDS:
        last_sms_status = "SKIPPED_COOLDOWN"
        return False

    try:
        mail = MIMEText(message)
        mail["Subject"] = "🚨 EleGuard AI - CRITICAL Elephant Alert"
        mail["From"] = EMAIL_SENDER
        mail["To"] = EMAIL_RECIPIENT

        with smtplib.SMTP(EMAIL_SMTP_HOST, EMAIL_SMTP_PORT) as server:
            server.starttls()
            server.login(EMAIL_SENDER, EMAIL_APP_PASSWORD)
            server.sendmail(EMAIL_SENDER, EMAIL_RECIPIENT, mail.as_string())

        last_sms_time = now
        last_sms_status = "SENT"
        return True

    except Exception as error:
        print("⚠️ Email alert send failed:", error)
        last_sms_status = "FAILED"
        return False


@app.get("/api/sms-status")
def get_sms_status():
    return {
        "enabled": EMAIL_ENABLED,
        "package_installed": True,
        "last_status": last_sms_status
    }


# =========================================================
# FIXED HEC RISK ENGINE
# =========================================================
#
# Risk score is based primarily on elephant movement.
# IoT values (vibration, temperature, battery, motion) do not
# randomly change the main risk score - stable, predictable demo.
#
# STEP 3 FIX: "MOVING" (elephant moving while still inside the
# forest zone, heading toward the village but not yet approaching
# it) is downgraded from HIGH to MEDIUM. It was confusing to see
# risk jump to HIGH for an elephant that's still deep in the
# forest. Now the levels read cleanly:
#   IN FOREST / MOVING (still in forest)  -> MEDIUM
#   APPROACHING VILLAGE                    -> HIGH
#   NEAR VILLAGE                           -> CRITICAL
# =========================================================

def calculate_current_risk():

    elephant_detected = bool(latest_detection_data.get("elephant_detected", False))
    movement = str(latest_detection_data.get("movement", "NO MOVEMENT")).upper().strip()
    location = str(latest_detection_data.get("location", "NO ELEPHANT")).upper().strip()

    if not elephant_detected:
        result = {
            "risk_score": 10,
            "risk_level": "LOW",
            "reasons": ["No elephant detected"],
            "recommended_action": "NO ACTION REQUIRED",
            "movement": "NO MOVEMENT"
        }

    else:

        if movement == "IN FOREST":
            risk_score, risk_level, action = 45, "MEDIUM", "MONITOR AREA"
            reasons = ["Elephant detected", "Elephant is inside forest"]

        elif movement == "MOVING":
            # STEP 3: downgraded HIGH(60) -> MEDIUM(55). Still inside the
            # forest zone, just heading toward the village - not yet an
            # elevated threat, so treat it the same tier as STATIONARY.
            risk_score, risk_level, action = 55, "MEDIUM", "MONITOR AREA"
            reasons = ["Elephant detected", "Elephant is moving within the forest"]

        elif movement == "APPROACHING VILLAGE":
            risk_score, risk_level, action = 75, "HIGH", "ACTIVATE WARNING"
            reasons = ["Elephant detected", "Elephant approaching village"]

        elif movement == "NEAR VILLAGE":
            risk_score, risk_level, action = 95, "CRITICAL", "ACTIVATE ALERT AND WARNING SYSTEM"
            reasons = ["Elephant detected", "Elephant near village"]

        elif movement == "MOVING AWAY":
            risk_score, risk_level, action = 40, "MEDIUM", "MONITOR AREA"
            reasons = ["Elephant detected", "Elephant moving away"]

        elif movement == "STATIONARY":
            risk_score, risk_level, action = 50, "MEDIUM", "MONITOR AREA"
            reasons = ["Elephant detected", "Elephant stationary"]

        else:
            risk_score, risk_level, action = 45, "MEDIUM", "MONITOR AREA"
            reasons = ["Elephant detected", "Movement being monitored"]

        risk_score = max(0, min(risk_score, 100))

        result = {
            "risk_score": risk_score,
            "risk_level": risk_level,
            "reasons": reasons,
            "recommended_action": action,
            "movement": movement
        }

    # =====================================================
    # HUMAN + ELEPHANT SAME-ZONE SAFETY OVERRIDE
    # =====================================================
    # A human and the primary elephant in the same zone is an
    # immediate conflict condition. Never downgrade this to WARNING.
    human_sightings = latest_detection_data.get("human_sightings", [])
    primary_human_same_zone = any(
        isinstance(h, dict)
        and str(h.get("location", "")).upper().strip() == location
        for h in human_sightings
    ) if isinstance(human_sightings, list) else False

    if elephant_detected and primary_human_same_zone:
        result["risk_score"] = 100
        result["risk_level"] = "CRITICAL"
        result["recommended_action"] = "IMMEDIATE HUMAN SAFETY ALERT"
        result["reasons"] = [
            "Elephant detected",
            f"Human detected in the same zone ({location})",
            "Immediate human-elephant conflict risk"
        ]
        result["human_elephant_conflict"] = True
    else:
        result["human_elephant_conflict"] = False

    # ---- extra features layered on top (additive, non-breaking) ----
    elephant_count = int(latest_detection_data.get("elephant_count", 0))

    result["explanation"] = build_explanation(
        elephant_detected, result["movement"], location, result["risk_level"], elephant_count
    )
    if result.get("human_elephant_conflict"):
        result["explanation"] = (
            f"CRITICAL because a human and elephant are detected in the same zone "
            f"('{location}'). Immediate human safety action is required."
        )
    result["safe_route"] = get_safe_route(result["risk_level"])
    result["voice_alert"] = get_voice_alert(result["risk_level"], location)
    result["prediction"] = predict_movement()
    result["alert_targets"] = get_alert_targets(result["risk_level"])
    result["elephants"] = latest_detection_data.get("elephants", [])
    result["human_sightings"] = latest_detection_data.get("human_sightings", [])
    result["human_count"] = int(latest_detection_data.get("human_count", 0))

    return result


# =========================================================
# GET RISK
# =========================================================

@app.get("/api/risk")
def get_risk():
    return calculate_current_risk()


# =========================================================
# GET ACTUATOR STATUS  (also logs alert history as a side effect,
# since the frontend already polls this endpoint every second)
# =========================================================

def log_alert_if_needed(mode, risk_score, reasons, targets):

    global last_alert_state, last_alert_log_time, last_critical_log_time, critical_alert_active

    now = datetime.now()
    should_log = False
    previous_state = last_alert_state

    # CRITICAL is logged only when the system ENTERS CRITICAL.
    # Continuous CRITICAL polling will not create duplicate entries.
    if mode == "CRITICAL":
        if not critical_alert_active:
            should_log = True
            critical_alert_active = True

    else:
        # Leaving CRITICAL resets the active state.
        # A future return to CRITICAL will create a new alert.
        critical_alert_active = False

        if mode != last_alert_state:
            if (
                last_alert_log_time is None
                or (now - last_alert_log_time).total_seconds() >= ALERT_MODE_COOLDOWN_SECONDS
            ):
                should_log = True

        elif (
            last_alert_log_time is None
            or (now - last_alert_log_time).total_seconds() > 15
        ):
            should_log = True

    if should_log:
        entry = {
            "timestamp": now.isoformat(),
            "time": now.strftime("%H:%M:%S"),
            "mode": mode,
            "risk_score": risk_score,
            "message": "; ".join(reasons) if reasons else mode,
            "target": targets
        }
        alert_history.append(entry)

        if len(alert_history) > MAX_ALERT_HISTORY:
            del alert_history[0]
        try:
            save_alert(entry)
        except Exception as _e:
            print(f"⚠️ save_alert DB error: {_e}")

        last_alert_state = mode
        last_alert_log_time = now

        if mode == "CRITICAL":
            last_critical_log_time = now

        # Send the existing email only when CRITICAL is newly entered.
        if mode == "CRITICAL" and previous_state != "CRITICAL":
            if any(str(h.get("location","")).upper().strip() == str(latest_detection_data.get("location","")).upper().strip() for h in latest_detection_data.get("human_sightings", []) if isinstance(h, dict)):
                sms_text = (
                    f"EleGuard CRITICAL: Human and elephant are in the same zone "
                    f"({latest_detection_data.get('location', 'UNKNOWN')}). Risk score {risk_score}/100. Immediate safety action required."
                )
            else:
                sms_text = (
                    f"EleGuard ALERT: Elephant NEAR VILLAGE! "
                    f"Risk score {risk_score}/100. Take immediate precaution."
                )
            send_sms_alert(sms_text)

@app.get("/api/actuators")
def get_actuator_status():

    risk = calculate_current_risk()

    risk_score = risk["risk_score"]
    risk_level = risk["risk_level"]

    if risk_level == "CRITICAL":
        buzzer, led, alert, mode = True, True, True, "CRITICAL"

    elif risk_level == "HIGH":
        buzzer, led, alert, mode = False, True, True, "WARNING"

    elif risk_level == "MEDIUM":
        buzzer, led, alert, mode = False, False, False, "MONITOR"

    else:
        buzzer, led, alert, mode = False, False, False, "NORMAL"

    log_alert_if_needed(mode, risk_score, risk["reasons"], risk.get("alert_targets", []))

    return {
        "risk_score": risk_score,
        "mode": mode,
        "buzzer": buzzer,
        "led": led,
        "alert": alert
    }


# =========================================================
# ALERT HISTORY
# =========================================================

@app.get("/api/alerts")
def get_alert_history():
    return {
        "total_events": len(alert_history),
        "events": alert_history[-20:]
    }


# =========================================================
# FALSE ALARM TRACKING (feature 31)
# =========================================================

@app.post("/api/alerts/false-alarm")
def report_false_alarm():

    global false_alarm_count
    false_alarm_count += 1

    fa_entry = {
        "timestamp": datetime.now().isoformat(),
        "time": datetime.now().strftime("%H:%M:%S"),
        "mode": "FALSE_ALARM",
        "risk_score": 0,
        "message": "Marked as false alarm by operator",
        "target": []
    }
    alert_history.append(fa_entry)
    try:
        save_alert(fa_entry)
    except Exception as _e:
        print(f"⚠️ save_false_alarm DB error: {_e}")

    return {"false_alarm_count": false_alarm_count}


# =========================================================
# DETECTION HISTORY (feature 27)
# =========================================================

@app.get("/api/detections/history")
def get_detection_history():
    return {
        "total": len(detection_history),
        "events": detection_history[-50:]
    }


# =========================================================
# CONFLICT HEATMAP (feature 28)
# =========================================================

@app.get("/api/analytics/heatmap")
def get_heatmap():

    bins = [0] * 10  # 10 buckets across x_position 0..1

    for event in detection_history:
        if not event.get("elephant_detected"):
            continue

        x = max(0.0, min(0.999, float(event.get("x_position", 0))))
        bucket = int(x * 10)
        bins[bucket] += 1

    return {
        "bins": [
            {
                "range": f"{i * 10}%-{(i + 1) * 10}%",
                "count": bins[i]
            }
            for i in range(10)
        ]
    }


# =========================================================
# RISK / HIGH-RISK-TIME STATISTICS (feature 29/30)
# =========================================================

@app.get("/api/analytics/stats")
def get_stats():

    scores = [e["risk_score"] for e in alert_history if "risk_score" in e]

    critical_events = sum(1 for e in alert_history if e.get("mode") == "CRITICAL")
    warning_events = sum(1 for e in alert_history if e.get("mode") == "WARNING")

    hour_counts = {}
    for e in alert_history:
        if e.get("mode") in ("CRITICAL", "WARNING"):
            hour = e["timestamp"][11:13]  # "HH" from ISO timestamp
            hour_counts[hour] = hour_counts.get(hour, 0) + 1

    peak_hour = max(hour_counts, key=hour_counts.get) if hour_counts else None

    return {
        "total_alert_events": len(alert_history),
        "critical_events": critical_events,
        "warning_events": warning_events,
        "avg_risk_score": round(sum(scores) / len(scores), 1) if scores else 0,
        "max_risk_score": max(scores) if scores else 0,
        "false_alarm_count": false_alarm_count,
        "peak_risk_hour": peak_hour
    }
