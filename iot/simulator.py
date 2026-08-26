import random
import time
import json
import os
import requests

API = os.getenv("API_BASE_URL", "http://127.0.0.1:8000")
SENSOR_API = f"{API}/api/sensors"
DETECTION_API = f"{API}/api/detection"

BATTERY_STATE_FILE = "battery_state.txt"


def load_battery():
    if os.path.exists(BATTERY_STATE_FILE):
        try:
            with open(BATTERY_STATE_FILE, "r") as f:
                return max(0, min(100, int(f.read().strip())))
        except Exception:
            return 100
    return 100


def save_battery(value):
    try:
        with open(BATTERY_STATE_FILE, "w") as f:
            f.write(str(value))
    except Exception:
        pass

battery = load_battery()
_battery_tick = 0

# Smooth sensor values so the dashboard does not jump unrealistically
# every 2 seconds while keeping the existing movement-dependent ranges.
_last_vibration = None
_last_temperature = None


def get_elephant_state():
    try:
        response = requests.get(DETECTION_API, timeout=2)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException:
        return {
            "elephant_detected": False,
            "movement": "NO MOVEMENT",
            "location": "NO ELEPHANT"
        }


def _smooth_int(previous, target, max_step):
    if previous is None:
        return target
    if target > previous:
        return min(target, previous + max_step)
    return max(target, previous - max_step)


def _smooth_float(previous, target, max_step):
    if previous is None:
        return target
    if target > previous:
        return min(target, previous + max_step)
    return max(target, previous - max_step)


def generate_sensor_data(detection=None):
    global battery, _battery_tick, _last_vibration, _last_temperature

    if detection is None:
        detection = get_elephant_state()

    elephant_detected = bool(detection.get("elephant_detected", False))

    movement = str(
        detection.get("movement", "NO MOVEMENT")
    ).upper().strip()

    location = str(
        detection.get("location", "NO ELEPHANT")
    ).upper().strip()

    if not elephant_detected:
        motion = False
        target_vibration = random.randint(0, 8)
        target_temperature = random.uniform(25.0, 27.5)
    elif movement == "MOVING AWAY":
        motion = True
        target_vibration = random.randint(20, 35)
        target_temperature = random.uniform(27.0, 29.0)
    elif movement == "STATIONARY":
        motion = False
        target_vibration = random.randint(10, 20)
        target_temperature = random.uniform(26.5, 29.0)
    elif movement == "MOVING":
        motion = True
        target_vibration = random.randint(40, 55)
        target_temperature = random.uniform(28.0, 30.0)
    elif movement == "APPROACHING VILLAGE":
        motion = True
        target_vibration = random.randint(60, 78)
        target_temperature = random.uniform(29.0, 31.5)
    elif movement == "NEAR VILLAGE":
        motion = True
        target_vibration = random.randint(85, 100)
        target_temperature = random.uniform(31.0, 34.0)
    else:
        motion = location != "NO ELEPHANT"
        target_vibration = random.randint(5, 15)
        target_temperature = random.uniform(26.0, 29.0)

    _last_vibration = _smooth_int(_last_vibration, target_vibration, 8)
    _last_temperature = _smooth_float(_last_temperature, target_temperature, 0.4)

    vibration = int(round(_last_vibration))
    temperature = round(_last_temperature, 1)

    _battery_tick += 1
    if _battery_tick % 3 == 0:
        battery = max(0, battery - random.choice([0, 0, 1]))
        save_battery(battery)

    return {
        "node_id": "NODE_01",
        "motion": motion,
        "vibration": vibration,
        "temperature": temperature,
        "battery": battery,
        "buzzer": False,
        "led": False
    }


while True:
    detection = get_elephant_state()
    sensor_data = generate_sensor_data(detection)

    try:
        response = requests.post(
            SENSOR_API,
            json=sensor_data,
            timeout=2
        )

        print("========================================")
        print("🐘 ELEPHANT STATE")
        print("Movement:", str(detection.get("movement", "NO MOVEMENT")))
        print("Location:", str(detection.get("location", "NO ELEPHANT")))
        print("\n📡 SENSOR DATA:")
        print(json.dumps(sensor_data, indent=2))
        print("\nSERVER RESPONSE:")
        print(response.json())

    except requests.exceptions.ConnectionError:
        print("❌ FastAPI server is not running")
    except requests.exceptions.RequestException as error:
        print("❌ Sensor API error:", error)

    time.sleep(2)
