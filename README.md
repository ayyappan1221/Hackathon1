# 🐘 EleGuard AI

**AI-powered Human–Elephant Conflict (HEC) Early Warning System**

EleGuard AI watches a camera feed with deep learning, tracks elephant movement toward human settlements, fuses IoT ground-sensor data, and warns villagers and forest officers **before** an encounter happens — through a live dashboard, voice alerts (Tamil + English), browser notifications, and automated email alerts.

> Prototype v2.0 · Built as a hackathon project · Merged from `C:\Users\Dharshini\Downloads\README.md` + full codebase analysis (`E:\Hackathon`)

---

## 🚨 The Problem

Human–Elephant Conflict kills hundreds of people and elephants every year across South India. Villages bordering forests rely on manual night patrols that are slow, dangerous, and expensive. By the time an elephant is spotted near a settlement, it is often too late.

**EleGuard AI's answer:** continuous AI surveillance + cheap sensor nodes (~₹15,000 per monitoring point) that detect, classify movement, predict where the elephant is heading, and escalate alerts automatically.

---

## 🏗️ Architecture

```
┌──────────────────────────┐      POST /api/detection        ┌─────────────────────────┐
│  ai/detect_and_send.py   │ ───────────────────────────────►│                         │
│  YOLO11n detection       │      POST /api/video-frame      │  backend/main.py        │
│  ByteTrack multi-object  │ ───────────────────────────────►│  FastAPI :8000          │
│  movement + zone logic   │                                 │  - risk engine          │
└──────────────────────────┘                                 │  - alert logging        │
                                                             │  - email escalation     │
┌──────────────────────────┐      POST /api/sensors          │  - MJPEG video relay    │
│  iot/simulator.py        │ ───────────────────────────────►│                         │
│  ESP32 node simulation   │                                 └───────────┬─────────────┘
│  (NODE_01)               │                                             │
└──────────────────────────┘                                             ▼
                                                           GET * (polled @1 Hz)
                                                              ┌─────────────────────────┐
                                                              │  frontend/ React 19     │
                                                              │  Live dashboard :5173   │
                                                              └─────────────────────────┘
```

**Detection pipeline (actual code `ai/detect_and_send.py:1`):** frame → `YOLO("yolo11n.pt")` `model.track(persist=True,tracker="bytetrack.yaml",conf=0.30)` every `PROCESS_Every_N_FRAMES=5` → per-elephant `position_history` deque(`HISTORY_SIZE=8`) → `compute_movement()` dx-based vs `MOVEMENT_THRESHOLD_RATIO=0.015*width` → `get_location()` zone (0.45/0.72) → `stabilize_state()` 3-frame debounce → pick most dangerous elephant by `MOVEMENT_RISK_PRIORITY` → POST `backend/main.py:333` `/api/detection` + base64 JPEG `VIDEO_STREAM_WIDTH=640` `JPEG_QUALITY=65` to `/api/video-frame` → GET `/api/camera/mode` polling for VIDEO↔CAMERA switch.

> **Note vs downloaded README:** downloaded README described `yolo11m.pt`, `imgsz=1280`, `augment=True/TTA`, `PROCESS_EVERY_N_FRAMES=2`, `CONFIDENCE=0.25` and `train_elephant_model.py`. Actual repository ships `ai/yolo11n.pt:5`, `CONFIDENCE_THRESHOLD=0.30:43`, `PROCESS_EVERY_N_FRAMES=5:32`, no explicit `imgsz`/`augment` args, and no `train_elephant_model.py` (see Project Structure below). The description above reflects the verified code.

---

## ✨ Features

### AI Detection (`ai/`)
- **YOLO11n** object detection — elephants (COCO 20), humans (0), vehicles (2,3,5,7 car/motorcycle/bus/truck) `ai/detect_and_send.py:405`
- **ByteTrack multi-object tracking** with persistent IDs across frames `ai/detect_and_send.py:344`
- **Multi-elephant support** — each elephant tracked independently (ID, confidence, movement, location); the most dangerous one drives aggregate risk `ai/detect_and_send.py:509`
- **Movement classification** — `IN FOREST` / `MOVING` / `APPROACHING VILLAGE` / `NEAR VILLAGE` / `STATIONARY` / `MOVING AWAY`, computed from normalized position history (resolution-independent)
- **Zone system** — `x < 0.45` FOREST · `< 0.72` APPROACHING VILLAGE · `≥ 0.72` NEAR VILLAGE `ai/detect_and_send.py:64` / `backend/main.py:88`
- Debounced state confirmation (`STATE_CONFIRMATION_FRAMES=3`) prevents flickering dashboard states `ai/detect_and_send.py:46`
- Hot-swappable input source: demo video `elephant.mp4` ↔ laptop webcam `CAMERA_INDEX=0`, controlled live from dashboard `frontend/src/App.jsx:118` via `GET/POST /api/camera/mode`
- Annotated frames streamed to dashboard via MJPEG relay `backend/main.py:506` + `ai/detect_and_send.py:363`

### Risk Engine & Alerts (`backend/`)
- Movement-driven risk scoring `backend/main.py:753`:

  | Situation | Score | Level |
  |---|---|---|
  | No elephant | 10 | LOW |
  | MOVING AWAY | 40 | MEDIUM |
  | IN FOREST | 45 | MEDIUM |
  | STATIONARY | 50 | MEDIUM |
  | MOVING | 55 | MEDIUM |
  | APPROACHING VILLAGE | 75 | HIGH |
  | NEAR VILLAGE | 95 | CRITICAL |
  | **Human + elephant in same zone** | **100** | **CRITICAL — IMMEDIATE SAFETY ALERT** `backend/main.py:816` |

- **Explainable AI output** — plain-language reason text `backend/main.py:650`
- **Movement prediction** — speed from recent history → predicted zone in 30 s + ETA to village `backend/main.py:530`
- **Safe route** + Tamil/English voice text `backend/main.py:613` / `backend/main.py:629`
- **Automated email alerts** to forest officers/villages when system enters CRITICAL (`SMS_COOLDOWN_SECONDS=60`, anti-flap `ALERT_MODE_COOLDOWN_SECONDS=8`, `CRITICAL` only on entry) `backend/main.py:872`
- Alert history, false-alarm reporting `POST /api/alerts/false-alarm`, detection/human-sighting history (dedup: `DETECTION_LOG_POSITION_DELTA=0.02`, `MIN_INTERVAL=1.5s`, `HEARTBEAT=3s` `backend/main.py:111`)
- Analytics: conflict heatmap (10 bins over x_position) `backend/main.py:1020`, event statistics `backend/main.py:1048`, peak hour, avg/max risk

### IoT Layer (`iot/`)
- Simulated ESP32 node (**NODE_01**) — PIR motion, vibration, temperature, solar/battery power `iot/simulator.py:69`
- Telemetry reacts to AI state (e.g., NEAR VILLAGE → vibration 85–100, temp 31–34 °C) with smoothing `_smooth_int/_smooth_float` `iot/simulator.py:53`
- Battery persisted to `iot/battery_state.txt:1` (decrements every 3 ticks) `iot/simulator.py:121`
- Node health monitoring (ONLINE/OFFLINE after `SENSOR_STALE_SECONDS=8`) `backend/main.py:300`, multi-node `GET /api/nodes`

### Dashboard (`frontend/`)
- 16-card live dashboard `frontend/src/App.jsx:1` (2176 LOC): IoT node, sensors, actuators, AI detections + multi-elephant list, HEC risk gauge, XAI box, live map with zones/markers/movement trail (last 5 points) `App.jsx:557`, prediction card, safe routes, heatmap (bar + strip), histories, event stats, cost card
- **Tamil voice alerts** (speechSynthesis `ta-IN`) on HIGH/CRITICAL `App.jsx:314`, critical beep (WebAudio) `App.jsx:258`, browser push notifications `App.jsx:385`
- Dark/light themes `App.jsx:234`, camera source toggle, offline banner `App.jsx:756`, MJPEG `<img src="/api/video-feed">` `App.jsx:1204`
- False-alarm button, cost/impact summary `App.jsx:2076`

---

## 📁 Project Structure

```
Hackathon/                           # E:\Hackathon (no git repo)
├── ai/
│   ├── detect_and_send.py           # YOLO detection + tracking + posting loop (575 LOC) - actual model yolo11n.pt
│   ├── yolo11n.pt                   # YOLO11 nano weights (verified, not yolo11m)
│   ├── elephant.mp4 / ele.mp4       # demo footage
│   └── elephant.jpeg
├── backend/
│   └── main.py                      # FastAPI server - all endpoints + risk engine (1071 LOC)
├── iot/
│   ├── simulator.py                 # NODE_01 telemetry simulator (161 LOC)
│   └── battery_state.txt            # persisted simulated battery (currently "1")
├── frontend/
│   ├── src/App.jsx                  # dashboard - single-component React app (2176 LOC)
│   ├── src/App.css                  # 1708 LOC (contains duplicated theme/trail blocks)
│   ├── src/index.css / main.jsx / assets/
│   ├── index.html, vite.config.js, package.json  # React 19.2.8 + Vite 8.2.0 + oxlint 1.75.0
│   ├── public/ assets
│   └── README.md                    # Vite template readme (untouched)
├── schedule.docx
├── WhatsApp Image 2026-08-24 ...jpeg
└── README.md                        # ← this file (merged)
```

> Downloaded README referenced `ai/train_elephant_model.py` and `yolo11m.pt`/`yolo11n.pt (legacy)` — neither `train_elephant_model.py` nor `yolo11m.pt` exists in the checked repository. Verified file list via `Get-ChildItem -Recurse`.

---

## 🚀 Getting Started

### Prerequisites
- Python 3.10+
- Node.js 18+
- A webcam (optional — demo video works out of the box)

### 1. Backend

```bash
cd backend
pip install fastapi uvicorn[standard] python-multipart
uvicorn main:app --reload --port 8000
```
CORS allows `http://localhost:5173` and `http://127.0.0.1:5173` `backend/main.py:28`.

### 2. AI Detection

```bash
cd ai
pip install ultralytics opencv-python requests
python detect_and_send.py
```

On first run model weights are loaded locally (`yolo11n.pt` already present). Script loops demo video continuously (`cap.set(CAP_PROP_POS_FRAMES,0)` `ai/detect_and_send.py:317`); switch to laptop webcam from dashboard.

> **Fix before running:** `ai/detect_and_send.py` uses `time.sleep()` at lines 304/310/331 but missing `import time` → add `import time` to imports or the mode-switch loop crashes with `NameError`.

### 3. IoT Simulator (optional but recommended)

```bash
cd iot
pip install requests
python simulator.py
```

### 4. Frontend

```bash
cd frontend
npm install
npm run dev
```

Open **http://localhost:5173**

**Start-up order matters:** backend → AI → IoT → frontend.

---

## ⚙️ Key Configuration

### `ai/detect_and_send.py`
| Setting | Actual Default | Purpose | Downloaded README claimed |
|---|---|---|---|
| `MODEL_PATH` | `"yolo11n.pt"` | Model size vs accuracy | `"yolo11m.pt"` |
| `CONFIDENCE_THRESHOLD` | `0.30` | Lower catches weak detections | `0.25` |
| `PROCESS_EVERY_N_FRAMES` | `5` | Frames skipped between inference | `2` |
| `HISTORY_SIZE` | `8` | Per-elephant position window | — |
| `MOVEMENT_THRESHOLD_RATIO` | `0.015` | Resolution-independent threshold | — |
| `STATE_CONFIRMATION_FRAMES` | `3` | Debounce flicker | — |
| `VIDEO_STREAM_WIDTH` / `VIDEO_JPEG_QUALITY` | `640` / `65` | MJPEG payload size | — |

`IMG_SIZE=1280` and `augment=True (TTA)` mentioned in downloaded README are **not present** in current `detect_and_send.py`.

### `backend/main.py`
| Setting | Default | Purpose |
|---|---|---|
| `EMAIL_ENABLED` | `True` | Send email on CRITICAL entry `backend/main.py:72` |
| `EMAIL_SENDER / EMAIL_APP_PASSWORD / EMAIL_RECIPIENT` | hardcoded | Gmail SMTP `smtp.gmail.com:587` — **move to env vars** |
| `SMS_COOLDOWN_SECONDS` | `60` | Min seconds between alert emails |
| `SENSOR_STALE_SECONDS` | `8` | Mark node OFFLINE after silence |
| `ALERT_MODE_COOLDOWN_SECONDS` | `8` | Anti-flap for non-critical logs |
| `CRITICAL_REALERT_COOLDOWN_SECONDS` | `5` | (defined unused) |
| `FOREST_LIMIT / VILLAGE_LIMIT` | `0.45 / 0.72` | Zone thresholds |
| `DETECTION_LOG_POSITION_DELTA` / `HEARTBEAT` / `MIN_INTERVAL` | `0.02 / 3s / 1.5s` | Dedup history |

---

## 🔌 API Reference (FastAPI :8000) — Verified `backend/main.py`

| Method | Endpoint | Purpose |
|---|---|---|
| GET | `/` | Health `{"project":"EleGuard AI","status":"Backend Online"}` |
| POST | `/api/detection` | Receive AI detection payload `receive_detection_data:333` |
| GET | `/api/detection` | Latest detection state |
| POST | `/api/video-frame` | Push annotated frame (base64) `receive_video_frame:491` |
| GET | `/api/video-feed` | MJPEG live stream `video_feed:518` |
| GET/POST | `/api/camera/mode` | Switch VIDEO ↔ CAMERA `get/set_camera_mode:440` |
| GET | `/api/risk` | Current risk (+XAI, prediction, safe route) `calculate_current_risk:753` |
| GET | `/api/actuators` | Buzzer/LED/alert flags by risk level + logs alert `get_actuator_status:938` |
| GET | `/api/sensors` | Latest IoT telemetry + node health (NODE_01) |
| POST | `/api/sensors` | Submit telemetry `receive_sensor_data:248` |
| GET | `/api/nodes` | All registered nodes `get_all_nodes:311` |
| GET | `/api/alerts` | Recent alert history (20) `get_alert_history:973` |
| POST | `/api/alerts/false-alarm` | Report false alarm `report_false_alarm:985` |
| GET | `/api/detections/history` | Last 50 detections `get_detection_history:1007` |
| GET | `/api/humans/history` | Last 50 human sightings `get_human_history:192` |
| GET | `/api/analytics/heatmap` | Position-binned heatmap (10 bins) `get_heatmap:1019` |
| GET | `/api/analytics/stats` | Event totals, avg/max risk, peak hour `get_stats:1047` |
| GET | `/api/sms-status` | Email status `get_sms_status:726` |

---

## 🧠 Improving Detection Accuracy Further

The stock COCO model saw relatively few elephants (mostly African savanna). For maximum real-world accuracy, fine-tune on local footage:

1. Get labeled dataset (Roboflow Universe → "elephant detection" → export YOLOv11 format, or label ~300–1000 images yourself)
2. Create `ai/train_elephant_model.py` (currently missing) and set `DATASET_YAML`
3. `python train_elephant_model.py`
4. Point `MODEL_PATH` at `runs/detect/eleguard/weights/best.pt`

Performance tip: `yolo11n` @ 640 px is fastest; `yolo11m` @ 1280 px+TTA (as described in downloaded README) needs strong GPU. On weak hardware use `yolo11s.pt` and/or lower `VIDEO_STREAM_WIDTH`.

---

## ⚠️ Known Limitations (Merged)

From downloaded README + codebase audit:
- **All backend state is in-memory** — restarting clears `detection_history` (300), `human_sighting_history` (200), `alert_history` (200) — no database yet `backend/main.py:177`
- Track IDs reset when demo video loops or input switches — no re-ID `ai/detect_and_send.py:318`
- Frontend polls ~10-11 requests/second (every 1s) — fine for demos, WebSocket would scale better `frontend/src/App.jsx:208`
- Single dashboard component (`App.jsx`, 2176 lines) — ready for decomposition
- Email credentials hardcoded `backend/main.py:73` — **move to env vars before deploy/share**
- `iot/battery_state.txt` currently `1` (not `0` as README assumed) — edit to set starting charge
- **Bug:** missing `import time` in `ai/detect_and_send.py` despite 3 uses — crashes on camera switch
- **Deploy:** `API="http://127.0.0.1:8000"` hardcoded in `ai/`, `iot/`, `frontend/` — needs `VITE_API_URL` / env for production
- **Concurrency:** global mutable state + async `mjpeg_generator` not thread-safe
- **CSS:** `App.css` contains duplicated theme/trail blocks (lines ~1030 & ~1310); `index.css` `#root{width:1126px}` restricts dashboard `max-width:1500px`

---

## 🔭 Roadmap

- [ ] SQLite persistence for history/analytics
- [ ] WebSocket push instead of polling
- [ ] Real ESP32 firmware replacing simulator
- [ ] GSM/LoRa mesh for off-grid village nodes
- [ ] Night-vision / thermal camera support (fine-tuned low-light model)
- [ ] SMS gateway integration (Twilio/MSG91) — currently replaced by email due to Twilio trial limits `backend/main.py:55`
- [ ] Multi-node fusion — triangulate herds across cameras

---

## 💰 Cost & Impact

| Component | Cost (approx.) |
|---|---|
| IoT sensing node (ESP32 + PIR + vibration + temp + solar) | ₹3,500–4,500 |
| AI camera node (Raspberry Pi/Jetson + camera) | ₹8,000–12,000 |
| **Full monitoring point** | **~₹15,000** |

vs. manual patrol teams — and 5–10 nodes can cover an entire village boundary, 24/7, in any weather. See `frontend/src/App.jsx:2076` cost card.

---

*EleGuard AI • Prototype v2.0 • README merged 2026-08-26 from `Downloads/README.md` + verified codebase `E:\Hackathon`*
