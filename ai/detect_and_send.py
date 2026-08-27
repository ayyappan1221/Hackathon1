from ultralytics import YOLO
import requests
import cv2
import base64
import time
from collections import defaultdict, deque


# =========================================================
# ELEGUARD AI - ELEPHANT DETECTION + MOVEMENT TRACKING
# (MULTI-ELEPHANT VERSION)
# =========================================================

MODEL_PATH = "yolo11n.pt"
VIDEO_PATH = "elephant.mp4"

API_URL = "http://127.0.0.1:8000/api/detection"
VIDEO_FRAME_API = "http://127.0.0.1:8000/api/video-frame"
CAMERA_MODE_API = "http://127.0.0.1:8000/api/camera/mode"
CAMERA_INDEX = 0
MODE_CHECK_INTERVAL_FRAMES = 10

# Live video feed settings - keeps payload small so posting a frame
# every processed cycle doesn't slow down the detection loop.
VIDEO_STREAM_WIDTH = 640
VIDEO_JPEG_QUALITY = 65


# =========================================================
# SETTINGS
# =========================================================

PROCESS_EVERY_N_FRAMES = 5

# How many recent processed positions we keep PER elephant to
# judge direction. More than 2 smooths out jitter.
HISTORY_SIZE = 8

# Movement threshold as a FRACTION of frame width (resolution
# independent - fixed pixel thresholds broke on different videos).
MOVEMENT_THRESHOLD_RATIO = 0.015

CONFIDENCE_THRESHOLD = 0.30

# Require the same state for 2 processed frames before dashboard update.
# YOLO detection/tracking/video speed remain unchanged.
STATE_CONFIRMATION_FRAMES = 3

# COCO class ids we treat as "vehicle" for multi-object detection
VEHICLE_CLASS_IDS = {2, 3, 5, 7}  # car, motorcycle, bus, truck


# =========================================================
# LOCATION ZONES
# =========================================================
#
# Elephant moves LEFT -> RIGHT in our prototype video.
#
# 0.00 - 0.44  = FOREST
# 0.45 - 0.71  = APPROACHING VILLAGE
# 0.72 - 1.00  = NEAR VILLAGE
#
# =========================================================

FOREST_LIMIT = 0.45
VILLAGE_LIMIT = 0.72

# Used to pick which elephant is "most dangerous" when several are
# on screen at once - matches the risk engine's own scoring so the
# elephant closest to the village always drives the main alert.
MOVEMENT_RISK_PRIORITY = {
    "NEAR VILLAGE": 95,
    "APPROACHING VILLAGE": 75,
    "MOVING": 60,
    "STATIONARY": 50,
    "IN FOREST": 45,
    "MOVING AWAY": 40,
}


# =========================================================
# LOAD YOLO MODEL
# =========================================================

print("🤖 Loading YOLO model...")
model = YOLO(MODEL_PATH)
print("✅ YOLO model loaded")


# =========================================================
# INPUT SOURCE HELPERS
# =========================================================

current_mode = "VIDEO"
cap = None
frame_width = 0
frame_height = 0

def get_input_mode():
    try:
        response = requests.get(CAMERA_MODE_API, timeout=1)
        response.raise_for_status()
        mode = str(response.json().get("mode", "VIDEO")).upper().strip()
        return mode if mode in {"VIDEO", "CAMERA"} else "VIDEO"
    except requests.exceptions.RequestException:
        return current_mode


def open_input_source(mode):
    source = CAMERA_INDEX if mode == "CAMERA" else VIDEO_PATH
    new_cap = cv2.VideoCapture(source)

    if not new_cap.isOpened():
        new_cap.release()
        return None, 0, 0

    width = int(new_cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(new_cap.get(cv2.CAP_PROP_FRAME_HEIGHT))

    if width <= 0 or height <= 0:
        width, height = 640, 480

    return new_cap, width, height


def switch_input_source(mode):
    global cap, frame_width, frame_height, current_mode, MOVEMENT_THRESHOLD_PX

    if cap is not None:
        cap.release()

    new_cap, width, height = open_input_source(mode)

    if new_cap is None:
        cap = None
        frame_width = 0
        frame_height = 0
        # Keep the previous mode value so the main loop keeps retrying
        # the requested source instead of getting stuck after one failure.
        return False

    cap = new_cap
    frame_width = width
    frame_height = height
    current_mode = mode
    MOVEMENT_THRESHOLD_PX = MOVEMENT_THRESHOLD_RATIO * frame_width

    # Do not carry movement history from a video frame into a camera frame
    # or vice versa. This keeps direction/location synchronized after a mode switch.
    position_history.clear()
    state_stability.clear()

    if mode == "CAMERA":
        print(f"📷 Laptop camera opened successfully: {frame_width} x {frame_height}")
    else:
        print(f"🎥 Demo video opened successfully: {frame_width} x {frame_height}")

    print(f"📏 Movement threshold: {MOVEMENT_THRESHOLD_PX:.1f}px")
    return True


# =========================================================
# OPEN DEFAULT INPUT
# =========================================================

# Existing behavior remains VIDEO mode at startup.
# The dashboard can switch this live to CAMERA.


# =========================================================
# TRACKING VARIABLES
# =========================================================

frame_count = 0

# ONE history deque PER elephant track id, so every elephant on
# screen is followed independently instead of only the "active" one.
position_history = defaultdict(lambda: deque(maxlen=HISTORY_SIZE))

# Stabilization state used only for dashboard movement/location display.
state_stability = {}

# Open the existing demo video at startup.
if not switch_input_source("VIDEO"):
    print("❌ Could not open demo video")
    exit()

print("🐘 Starting YOLO elephant/human tracking (multi-object)...")
print()

# Track ids seen in the previous processed frame - anything missing
# this frame we simply stop updating (its history just goes stale).
# If YOLO later assigns a NEW id to the same physical elephant, it
# starts a fresh history under that id - a known limitation without
# a re-identification model, acceptable for a demo prototype.


# =========================================================
# HELPER FUNCTIONS
# =========================================================

def get_location(x_position):
    if x_position < FOREST_LIMIT:
        return "IN FOREST"
    elif x_position < VILLAGE_LIMIT:
        return "APPROACHING VILLAGE"
    else:
        return "NEAR VILLAGE"


def get_moving_toward_village_label(x_position):
    if x_position >= VILLAGE_LIMIT:
        return "NEAR VILLAGE"
    elif x_position >= FOREST_LIMIT:
        return "APPROACHING VILLAGE"
    else:
        return "MOVING"


def compute_movement(history, x_position, location):
    """
    Works out ONE elephant's movement label from ITS OWN position
    history (oldest vs newest sample in the rolling window).
    """

    if len(history) < 2:
        return "IN FOREST" if location == "IN FOREST" else "STATIONARY"

    oldest_x, oldest_y = history[0]
    newest_x, newest_y = history[-1]

    dx = newest_x - oldest_x
    dy = newest_y - oldest_y

    if abs(dx) < MOVEMENT_THRESHOLD_PX and abs(dy) < MOVEMENT_THRESHOLD_PX:
        return "IN FOREST" if location == "IN FOREST" else "STATIONARY"

    # The prototype video's village direction is LEFT -> RIGHT.
    # Use horizontal displacement only for toward/away classification.
    # Vertical camera movement must not turn into "MOVING AWAY".
    if dx > 0:
        return get_moving_toward_village_label(x_position)
    if dx < 0:
        return "MOVING AWAY"

    return "STATIONARY"


def stabilize_state(eid, raw_movement, raw_location):
    """Accept a changed state after 2 consecutive processed frames."""
    state = state_stability.get(eid)

    if state is None:
        state = {
            "movement": raw_movement,
            "location": raw_location,
            "candidate_movement": raw_movement,
            "candidate_location": raw_location,
            "movement_count": 1,
            "location_count": 1,
        }
        state_stability[eid] = state
        return raw_movement, raw_location

    if raw_movement == state["movement"]:
        state["candidate_movement"] = raw_movement
        state["movement_count"] = 0
    elif raw_movement == state["candidate_movement"]:
        state["movement_count"] += 1
        if state["movement_count"] >= STATE_CONFIRMATION_FRAMES:
            state["movement"] = raw_movement
            state["movement_count"] = 0
    else:
        state["candidate_movement"] = raw_movement
        state["movement_count"] = 1

    if raw_location == state["location"]:
        state["candidate_location"] = raw_location
        state["location_count"] = 0
    elif raw_location == state["candidate_location"]:
        state["location_count"] += 1
        if state["location_count"] >= STATE_CONFIRMATION_FRAMES:
            state["location"] = raw_location
            state["location_count"] = 0
    else:
        state["candidate_location"] = raw_location
        state["location_count"] = 1

    return state["movement"], state["location"]


# =========================================================
# MAIN LOOP
# =========================================================

while True:

    # Check the dashboard-selected input source periodically.
    if frame_count % MODE_CHECK_INTERVAL_FRAMES == 0:
        requested_mode = get_input_mode()
        if requested_mode != current_mode:
            print(f"🔄 Switching input source: {current_mode} -> {requested_mode}")
            if not switch_input_source(requested_mode):
                print("❌ Could not open requested input source")
                time.sleep(0.5)
                continue

    if cap is None:
        time.sleep(0.2)
        continue

    ret, frame = cap.read()

    if not ret:
        if current_mode == "VIDEO":
            # Loop the demo video instead of stopping, so the live
            # dashboard keeps showing continuous movement during a demo.
            cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
            position_history.clear()
            state_stability.clear()
            frame_count = 0
            print("🔁 Video ended - looping back to start for continuous demo")
            continue

        # Camera frames can temporarily fail. Re-open the webcam without
        # changing the selected mode or crashing the AI process.
        print("⚠️ Laptop camera frame unavailable - retrying...")
        cap.release()
        cap, frame_width, frame_height = open_input_source("CAMERA")
        if cap is None:
            time.sleep(0.5)
        else:
            MOVEMENT_THRESHOLD_PX = MOVEMENT_THRESHOLD_RATIO * frame_width
        continue

    frame_count += 1

    if frame_count % PROCESS_EVERY_N_FRAMES != 0:
        continue

    # =====================================================
    # YOLO TRACKING
    # =====================================================

    results = model.track(
        frame,
        persist=True,
        tracker="bytetrack.yaml",
        conf=CONFIDENCE_THRESHOLD,
        verbose=False
    )

    # =====================================================
    # LIVE VIDEO FEED
    # =====================================================
    #
    # Draw YOLO's boxes/labels onto the frame and send it to the
    # backend's MJPEG endpoint. This lets judges watch the actual
    # detection happen live inside the React dashboard - no need
    # for a desktop cv2.imshow() window, which wouldn't be visible
    # to anyone but the person running the script.
    # =====================================================

    try:
        annotated_frame = results[0].plot()

        # Resize down - keeps each HTTP post small and fast so the
        # detection loop itself never gets slowed down by streaming.
        h, w = annotated_frame.shape[:2]
        scale = VIDEO_STREAM_WIDTH / w
        annotated_frame = cv2.resize(
            annotated_frame, (VIDEO_STREAM_WIDTH, int(h * scale))
        )

        success, buffer = cv2.imencode(
            ".jpg", annotated_frame,
            [int(cv2.IMWRITE_JPEG_QUALITY), VIDEO_JPEG_QUALITY]
        )

        if success:
            frame_b64 = base64.b64encode(buffer).decode("utf-8")
            requests.post(VIDEO_FRAME_API, json={"frame": frame_b64}, timeout=1)

    except requests.exceptions.RequestException:
        pass  # never let a slow/failed frame post break detection
    except Exception as stream_error:
        print("⚠️ Video stream error:", stream_error)

    elephant_count = 0
    human_count = 0
    vehicle_count = 0
    elephant_confidences = []
    current_elephants = []  # raw YOLO boxes this frame
    current_humans = []  # raw human boxes this frame

    for result in results:

        if result.boxes is None:
            continue

        for box in result.boxes:

            class_id = int(box.cls[0])
            confidence = float(box.conf[0])

            track_id = None
            if box.id is not None:
                track_id = int(box.id[0])

            # COCO CLASS ID 20 = elephant
            if class_id == 20:

                elephant_count += 1
                elephant_confidences.append(confidence)

                x1, y1, x2, y2 = box.xyxy[0].tolist()
                center_x = (x1 + x2) / 2
                center_y = (y1 + y2) / 2

                current_elephants.append({
                    "id": track_id,
                    "x": center_x,
                    "y": center_y,
                    "confidence": confidence
                })

            # COCO CLASS ID 0 = human
            elif class_id == 0:
                human_count += 1
                x1, y1, x2, y2 = box.xyxy[0].tolist()
                center_x = (x1 + x2) / 2
                center_y = (y1 + y2) / 2
                human_id = track_id if track_id is not None else f"human_{len(current_humans)}"
                h_x_position = max(0.0, min(1.0, center_x / frame_width))
                h_y_position = max(0.0, min(1.0, center_y / frame_height))
                current_humans.append({
                    "id": str(human_id),
                    "x_position": round(h_x_position, 4),
                    "y_position": round(h_y_position, 4),
                    "location": get_location(h_x_position),
                    "confidence": round(confidence * 100, 2),
                })

            # Vehicles - car / motorcycle / bus / truck
            elif class_id in VEHICLE_CLASS_IDS:
                vehicle_count += 1

    elephant_confidence = (
        max(elephant_confidences) * 100
        if elephant_confidences else 0
    )

    elephant_detected = elephant_count > 0
    human_detected = human_count > 0

    elephants_output = []

    # Aggregate/"primary" fields - kept for backward compatibility
    # with the risk engine + live map marker, which only look at a
    # single movement/location/x/y. We fill these with whichever
    # elephant is currently the MOST DANGEROUS one.
    movement = "NO MOVEMENT"
    location = "NO ELEPHANT"
    x_position = 0.0
    y_position = 0.0
    primary_elephant_id = None

    # =====================================================
    # BUILD PER-ELEPHANT DATA
    # =====================================================

    if current_elephants:

        for index, elephant in enumerate(current_elephants):

            # Fall back to a per-frame synthetic id only if YOLO
            # gave none (rare with persist=True + bytetrack).
            eid = elephant["id"] if elephant["id"] is not None else f"untracked_{index}"

            current_x = elephant["x"]
            current_y = elephant["y"]

            e_x_position = max(0.0, min(1.0, current_x / frame_width))
            e_y_position = max(0.0, min(1.0, current_y / frame_height))

            history = position_history[eid]
            history.append((current_x, current_y))

            e_location = get_location(e_x_position)
            raw_movement = compute_movement(
                history, e_x_position, e_location
            )

            # Stabilize only movement/location shown to the dashboard.
            e_movement, e_location = stabilize_state(
                eid, raw_movement, e_location
            )

            elephants_output.append({
                "id": str(eid),
                "confidence": round(elephant["confidence"] * 100, 2),
                "movement": e_movement,
                "location": e_location,
                "x_position": round(e_x_position, 4),
                "y_position": round(e_y_position, 4),
            })

        # Pick the highest-risk elephant to drive the top-level
        # fields (and therefore the main risk engine + alerts).
        most_dangerous = max(
            elephants_output,
            key=lambda e: MOVEMENT_RISK_PRIORITY.get(e["movement"], 45)
        )

        movement = most_dangerous["movement"]
        location = most_dangerous["location"]
        x_position = most_dangerous["x_position"]
        y_position = most_dangerous["y_position"]
        primary_elephant_id = most_dangerous["id"]

    else:
        # No elephants this frame - drop any stale per-id history.
        position_history.clear()
        state_stability.clear()

    # =====================================================
    # FASTAPI PAYLOAD
    # =====================================================

    detection_data = {
        "elephant_detected": elephant_detected,
        "elephant_count": elephant_count,
        "elephant_confidence": round(elephant_confidence, 2),
        "human_detected": human_detected,
        "human_count": human_count,
        "human_sightings": current_humans,
        "vehicle_detected": vehicle_count > 0,
        "vehicle_count": vehicle_count,
        "movement": movement,
        "location": location,
        "x_position": round(x_position, 4),
        "y_position": round(y_position, 4),
        "primary_elephant_id": primary_elephant_id,
        "elephants": elephants_output,  # per-elephant breakdown
    }

    # =====================================================
    # SEND TO FASTAPI
    # =====================================================

    try:
        response = requests.post(API_URL, json=detection_data, timeout=2)

        print(
            f"Frame {frame_count} | "
            f"🐘 Elephants: {elephant_count} | "
            f"👤 Human: {human_count} | "
            f"🚗 Vehicle: {vehicle_count} | "
            f"Confidence: {elephant_confidence:.2f}% | "
            f"🧭 Primary movement: {movement} | "
            f"📍 Primary location: {location} | "
            f"API: {response.status_code}"
        )

    except requests.exceptions.RequestException as error:
        print("❌ FastAPI connection error:", error)


# =========================================================
# CLEANUP
# =========================================================

if cap is not None:
    cap.release()
print()
print("✅ AI input processing stopped")
