import { useEffect, useRef, useState } from "react";
import "./App.css";

const API = (import.meta.env.VITE_API_URL !== undefined && import.meta.env.VITE_API_URL !== "" ? import.meta.env.VITE_API_URL : (location.hostname === "localhost" || location.hostname === "127.0.0.1" ? "http://127.0.0.1:8000" : "")).replace(/\/+$/, "");

function App() {
  // =========================================================
  // STATES
  // =========================================================

  const [sensorData, setSensorData] = useState(null);
  const [detectionData, setDetectionData] = useState(null);
  const [riskData, setRiskData] = useState(null);
  const [actuatorData, setActuatorData] = useState(null);
  const [alertData, setAlertData] = useState(null);
  const [historyData, setHistoryData] = useState(null);
  const [heatmapData, setHeatmapData] = useState(null);
  const [statsData, setStatsData] = useState(null);
  const [smsData, setSmsData] = useState(null);
  const [humanHistoryData, setHumanHistoryData] = useState(null);

  // ---- INPUT SOURCE: existing demo video / laptop webcam ----
  const [cameraMode, setCameraMode] = useState("VIDEO");
  const [cameraBusy, setCameraBusy] = useState(false);
  const [cameraError, setCameraError] = useState("");

  // ---- DEMO MODE (built-in simulator) ----
  const [demoMode, setDemoMode] = useState(true);

  const [error, setError] = useState("");
  const [offline, setOffline] = useState(false);

  const lastSpokenRef = useRef("");
  const lastNotifiedLevelRef = useRef("");

  // ---- THEME TOGGLE ----
  const [theme, setTheme] = useState("dark");

  // ---- CRITICAL ALERT SOUND (fixed: non-interruptible) ----
  const [soundEnabled, setSoundEnabled] = useState(false);
  const audioCtxRef = useRef(null);
  const lastBeepLevelRef = useRef("");
  const isBeepingRef = useRef(false);
  const beepTimeoutRef = useRef(null);

  // ---- VOICE ALERT LOCK (non-interruptible + loop) ----
  const isVoiceSpeakingRef = useRef(false);
  const queuedVoiceRef = useRef(null);
  const voiceLoopTimeoutRef = useRef(null);
  const pendingResetRef = useRef(false);
  const riskDataRef = useRef(null);

  // Keep riskDataRef in sync so voice onend callback sees latest level
  useEffect(() => {
    riskDataRef.current = riskData;
  }, [riskData]);

  // ---- ELEPHANT MOVEMENT TRAIL ----
  const [trail, setTrail] = useState([]);

  const humanElephantConflict = Boolean(
    riskData?.human_elephant_conflict ?? false
  );

  // =========================================================
  // FETCH HELPERS
  // =========================================================

  const fetchSensorData = async () => {
    const res = await fetch(`${API}/api/sensors`);
    if (!res.ok) throw new Error("Sensor API error");
    setSensorData(await res.json());
  };

  const fetchDetectionData = async () => {
    const res = await fetch(`${API}/api/detection`);
    if (!res.ok) throw new Error("Detection API error");
    setDetectionData(await res.json());
  };

  const fetchRiskData = async () => {
    const res = await fetch(`${API}/api/risk`);
    if (!res.ok) throw new Error("Risk API error");
    setRiskData(await res.json());
  };

  const fetchActuatorData = async () => {
    const res = await fetch(`${API}/api/actuators`);
    if (!res.ok) throw new Error("Actuator API error");
    setActuatorData(await res.json());
  };

  const fetchAlertData = async () => {
    const res = await fetch(`${API}/api/alerts`);
    if (!res.ok) throw new Error("Alert API error");
    setAlertData(await res.json());
  };

  const fetchHistoryData = async () => {
    const res = await fetch(`${API}/api/detections/history`);
    if (!res.ok) throw new Error("History API error");
    setHistoryData(await res.json());
  };

  const fetchHeatmapData = async () => {
    const res = await fetch(`${API}/api/analytics/heatmap`);
    if (!res.ok) throw new Error("Heatmap API error");
    setHeatmapData(await res.json());
  };

  const fetchStatsData = async () => {
    const res = await fetch(`${API}/api/analytics/stats`);
    if (!res.ok) throw new Error("Stats API error");
    setStatsData(await res.json());
  };

  const fetchHumanHistoryData = async () => {
    try {
      const res = await fetch(`${API}/api/humans/history`);
      if (res.ok) {
        setHumanHistoryData(await res.json());
      }
    } catch (err) {
      console.error("Human history fetch failed:", err);
    }
  };

  const fetchCameraMode = async () => {
    const res = await fetch(`${API}/api/camera/mode`);
    if (!res.ok) throw new Error("Camera mode API error");
    const data = await res.json();
    setCameraMode(data?.mode === "CAMERA" ? "CAMERA" : "VIDEO");
  };

  const toggleCameraMode = async () => {
    if (cameraBusy) return;

    const nextMode = cameraMode === "CAMERA" ? "VIDEO" : "CAMERA";
    setCameraBusy(true);
    setCameraError("");

    try {
      const res = await fetch(`${API}/api/camera/mode`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ mode: nextMode }),
      });

      if (!res.ok) {
        throw new Error("Could not change camera mode");
      }

      const data = await res.json();
      setCameraMode(data?.mode === "CAMERA" ? "CAMERA" : "VIDEO");
    } catch (err) {
      console.error("Camera mode switch failed:", err);
      setCameraError("Camera mode switch failed");
    } finally {
      setCameraBusy(false);
    }
  };

  const fetchDemoStatus = async () => {
    try {
      const res = await fetch(`${API}/api/demo/status`);
      if (res.ok) {
        const data = await res.json();
        setDemoMode(data.demo_mode);
      }
    } catch (_) {}
  };

  const toggleDemoMode = async () => {
    try {
      const res = await fetch(`${API}/api/demo/toggle`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({}),
      });
      if (res.ok) {
        const data = await res.json();
        setDemoMode(data.demo_mode);
      }
    } catch (err) {
      console.error("Demo toggle failed:", err);
    }
  };

  const fetchSmsData = async () => {
    try {
      const res = await fetch(`${API}/api/sms-status`);

      if (res.ok) {
        setSmsData(await res.json());
      }
    } catch (err) {
      console.error("SMS status fetch failed:", err);
    }
  };

  const reportFalseAlarm = async () => {
    try {
      await fetch(`${API}/api/alerts/false-alarm`, {
        method: "POST",
      });

      fetchStatsData();
      fetchAlertData();
    } catch (err) {
      console.error("False alarm report failed:", err);
    }
  };

  // =========================================================
  // FETCH ALL DATA
  // =========================================================

  const fetchAllData = async () => {
    try {
      await Promise.all([
        fetchSensorData(),
        fetchDetectionData(),
        fetchRiskData(),
        fetchActuatorData(),
        fetchAlertData(),
        fetchHistoryData(),
        fetchHeatmapData(),
        fetchStatsData(),
        fetchHumanHistoryData(),
        fetchCameraMode(),
        fetchDemoStatus(),
      ]);

      fetchSmsData();

      setError("");
      setOffline(false);
    } catch (err) {
      console.error("Dashboard error:", err);
      setError("Backend connection lost");
      setOffline(true);
    }
  };

  // =========================================================
  // INITIAL LOAD + AUTO REFRESH
  // =========================================================

  useEffect(() => {
    fetchAllData();

    const interval = setInterval(fetchAllData, 1000);

    return () => clearInterval(interval);
  }, []);

  // =========================================================
  // BROWSER PUSH NOTIFICATIONS
  // =========================================================

  useEffect(() => {
    if (
      "Notification" in window &&
      Notification.permission === "default"
    ) {
      Notification.requestPermission();
    }
  }, []);

  // =========================================================
  // LIGHT / DARK THEME
  // =========================================================

  useEffect(() => {
    document.documentElement.setAttribute("data-theme", theme);
  }, [theme]);

  const toggleTheme = () => {
    setTheme((prev) => (prev === "dark" ? "light" : "dark"));
  };

  // =========================================================
  // CRITICAL ALERT BEEP SOUND
  // =========================================================

  const enableSound = () => {
    try {
      const Ctx =
        window.AudioContext || window.webkitAudioContext;

      if (!audioCtxRef.current) {
        audioCtxRef.current = new Ctx();
      }

      audioCtxRef.current.resume();
      setSoundEnabled(true);
    } catch (err) {
      console.error("Could not enable audio:", err);
    }
  };

  const playCriticalBeep = () => {
    let ctx = audioCtxRef.current;

    if (!ctx) {
      try {
        const Ctx = window.AudioContext || window.webkitAudioContext;
        ctx = new Ctx();
        audioCtxRef.current = ctx;
      } catch {
        return;
      }
    }

    // Resume if suspended (browser autoplay policy / tab hidden)
    if (ctx.state === "suspended") {
      ctx.resume().catch(() => {});
    }

    // Non-interruptible lock: don't restart a beep that is already playing
    // This guarantees the 3-beep sequence (~1.05s) finishes even if risk
    // drops to LOW/MEDIUM mid-sequence.
    if (isBeepingRef.current) return;
    isBeepingRef.current = true;

    const now = ctx.currentTime;

    [0, 0.35, 0.7].forEach((offset) => {
      const osc = ctx.createOscillator();
      const gain = ctx.createGain();

      osc.type = "square";
      osc.frequency.value = 1000;

      gain.gain.setValueAtTime(0.0001, now + offset);
      gain.gain.exponentialRampToValueAtTime(0.3, now + offset + 0.02);
      gain.gain.exponentialRampToValueAtTime(0.0001, now + offset + 0.28);

      osc.connect(gain);
      gain.connect(ctx.destination);

      // Fire-and-forget: scheduled start/stop will complete even if React
      // state changes to LOW before the sequence finishes. We never call
      // osc.stop() early or disconnect on risk change.
      try {
        osc.start(now + offset);
        osc.stop(now + offset + 0.3);
      } catch {
        // Oscillator already started/stopped - ignore
      }
    });

    // Release lock after the full sequence finishes (1.05s) so next
    // CRITICAL entry can beep again, but current sequence never gets cut.
    if (beepTimeoutRef.current) clearTimeout(beepTimeoutRef.current);
    beepTimeoutRef.current = setTimeout(() => {
      isBeepingRef.current = false;
    }, 1100);
  };

  useEffect(() => {
    const level = riskData?.risk_level;

    if (!level) return;

    if (
      soundEnabled &&
      level === "CRITICAL" &&
      lastBeepLevelRef.current !== "CRITICAL"
    ) {
      playCriticalBeep();
    }

    lastBeepLevelRef.current = level;
  }, [riskData?.risk_level, soundEnabled]);

  // Cleanup beep lock on unmount so timeout doesn't leak
  useEffect(() => {
    return () => {
      if (beepTimeoutRef.current) clearTimeout(beepTimeoutRef.current);
      if (voiceLoopTimeoutRef.current) clearTimeout(voiceLoopTimeoutRef.current);
    };
  }, []);

  // Helper: speak Tamil voice fully without interruption - queues next only after onend
  const speakVoiceLocked = (tamilText) => {
    if (!tamilText || !("speechSynthesis" in window)) return;

    // If already speaking, queue the latest request - will play after current finishes
    if (isVoiceSpeakingRef.current || window.speechSynthesis.speaking) {
      queuedVoiceRef.current = tamilText;
      return;
    }

    // Cancel any pending loop timeout before starting new utterance
    if (voiceLoopTimeoutRef.current) {
      clearTimeout(voiceLoopTimeoutRef.current);
      voiceLoopTimeoutRef.current = null;
    }

    isVoiceSpeakingRef.current = true;
    queuedVoiceRef.current = null;

    const voices = window.speechSynthesis.getVoices();
    const tamilVoice =
      voices.find((v) => v.lang.toLowerCase() === "ta-in") ||
      voices.find((v) => v.lang.toLowerCase().startsWith("ta"));

    const utterance = new SpeechSynthesisUtterance(tamilText);
    utterance.lang = "ta-IN";
    utterance.rate = 0.9;
    utterance.pitch = 1;
    utterance.volume = 1;
    if (tamilVoice) utterance.voice = tamilVoice;

    const onFinish = () => {
      isVoiceSpeakingRef.current = false;
      lastSpokenRef.current = tamilText;

      // Handle deferred reset if risk dropped to LOW while we were speaking
      if (pendingResetRef.current) {
        pendingResetRef.current = false;
        lastSpokenRef.current = "";
        // don't loop after reset
        return;
      }

      // 1. If a newer alert was queued while we were speaking, play it next (no cancel, just queue)
      if (queuedVoiceRef.current) {
        const next = queuedVoiceRef.current;
        queuedVoiceRef.current = null;
        // ignore reset marker, already handled
        if (next === "__RESET__") return;
        voiceLoopTimeoutRef.current = setTimeout(() => speakVoiceLocked(next), 350);
        return;
      }

      // 2. LOOP: if risk still HIGH/CRITICAL, repeat same voice after gap - ensures each utterance completes fully
      const currentLevel = riskDataRef.current?.risk_level;
      if (currentLevel && ["HIGH", "CRITICAL"].includes(currentLevel)) {
        // Rebuild text for current level in case it changed HIGH<->CRITICAL while speaking
        let loopText = "";
        if (currentLevel === "CRITICAL") loopText = "எச்சரிக்கை! யானை கிராமத்திற்கு அருகில் உள்ளது.";
        else if (currentLevel === "HIGH") loopText = "எச்சரிக்கை! யானை கிராமத்தை நோக்கி வருகிறது.";
        if (loopText) {
          voiceLoopTimeoutRef.current = setTimeout(() => {
            // Only loop if still in alert and not already speaking
            const lvl = riskDataRef.current?.risk_level;
            if (lvl && ["HIGH", "CRITICAL"].includes(lvl) && !isVoiceSpeakingRef.current && !window.speechSynthesis.speaking) {
              speakVoiceLocked(loopText);
            } else if (lvl && ["HIGH", "CRITICAL"].includes(lvl)) {
              queuedVoiceRef.current = loopText;
            }
          }, 3500); // 3.5s gap between loops - enough for gap, avoids spam, guarantees completion
        }
      }
    };

    utterance.onend = onFinish;
    utterance.onerror = () => {
      isVoiceSpeakingRef.current = false;
      if (pendingResetRef.current) {
        pendingResetRef.current = false;
        lastSpokenRef.current = "";
        return;
      }
      // don't auto-retry on error, just allow next trigger
      if (queuedVoiceRef.current) {
        const next = queuedVoiceRef.current;
        queuedVoiceRef.current = null;
        if (next === "__RESET__") return;
        voiceLoopTimeoutRef.current = setTimeout(() => speakVoiceLocked(next), 350);
      }
    };

    // NEVER call speechSynthesis.cancel() - that cuts the current voice mid-sentence
    window.speechSynthesis.speak(utterance);
  };

  // =========================================================
  // VOICE ALERT - TAMIL (non-interruptible + loop)
  // =========================================================

  useEffect(() => {
    const level = riskData?.risk_level;

    if (
      !level ||
      !["HIGH", "CRITICAL"].includes(level) ||
      !("speechSynthesis" in window)
    ) {
      if (
        !level ||
        !["HIGH", "CRITICAL"].includes(level)
      ) {
        // Risk dropped to LOW/MEDIUM: let current utterance finish (don't cancel),
        // but clear queue and stop looping - next trigger will be fresh
        queuedVoiceRef.current = null;
        if (voiceLoopTimeoutRef.current) {
          clearTimeout(voiceLoopTimeoutRef.current);
          voiceLoopTimeoutRef.current = null;
        }
        // Reset so next HIGH/CRITICAL entry can speak again even if same text
        // Wait until current voice actually finishes - don't reset lastSpoken immediately if still speaking
        if (!isVoiceSpeakingRef.current && !window.speechSynthesis.speaking) {
          lastSpokenRef.current = "";
        } else {
          // Defer reset until onend - mark for reset (don't use queuedVoice, use dedicated flag)
          pendingResetRef.current = true;
        }
        return;
      }
      return;
    }

      // Handle deferred reset from previous LOW (if we set pending while speaking, wait until finished)
      if (pendingResetRef.current && !isVoiceSpeakingRef.current && !window.speechSynthesis.speaking) {
        lastSpokenRef.current = "";
        pendingResetRef.current = false;
        queuedVoiceRef.current = null;
      }

      let tamilText = "";

      if (level === "CRITICAL") {
        tamilText =
          "எச்சரிக்கை! யானை கிராமத்திற்கு அருகில் உள்ளது.";
      } else if (level === "HIGH") {
        tamilText =
          "எச்சரிக்கை! யானை கிராமத்தை நோக்கி வருகிறது.";
      }

      // Only trigger if text changed vs last fully-spoken, OR if loop needs to start
      // If same text already spoken and currently not speaking and no loop active, don't re-trigger immediately
      // The loop is handled by onend callback, so here we only handle level/text changes
      if (
        tamilText &&
        tamilText !== lastSpokenRef.current
      ) {
        speakVoiceLocked(tamilText);
      } else if (
        tamilText &&
        tamilText === lastSpokenRef.current &&
        !isVoiceSpeakingRef.current &&
        !window.speechSynthesis.speaking &&
        !voiceLoopTimeoutRef.current &&
        !queuedVoiceRef.current
      ) {
        // Edge: lastSpoken equals current but voice stopped and loop not scheduled (e.g., after manual cancel)
        // Re-initiate loop
        speakVoiceLocked(tamilText);
      }
    // Include riskDataRef sync dependency - humanElephantConflict still triggers re-eval
  }, [riskData?.risk_level, humanElephantConflict]);

  // =========================================================
  // BROWSER PUSH NOTIFICATION
  // =========================================================

  useEffect(() => {
    const level = riskData?.risk_level;

    if (!level) return;

    const isAlertLevel =
      level === "CRITICAL" || level === "HIGH";

    if (
      isAlertLevel &&
      level !== lastNotifiedLevelRef.current
    ) {
      if (
        "Notification" in window &&
        Notification.permission === "granted"
      ) {
        new Notification("🐘 EleGuard AI Alert", {
          body: humanElephantConflict
            ? `${level} RISK - Human and elephant are in the same zone (${detectionData?.location ?? "unknown"})`
            : `${level} RISK - ${riskData?.movement ?? "Elephant"} near ${detectionData?.location ?? "unknown location"}`,
          tag: "eleguard-alert",
        });
      }

      lastNotifiedLevelRef.current = level;
    }

    if (!isAlertLevel) {
      lastNotifiedLevelRef.current = "";
    }
  }, [
    riskData?.risk_level,
    humanElephantConflict,
  ]);

  // =========================================================
  // SAFE SENSOR VALUES
  // =========================================================

  const nodeId =
    sensorData?.node_id ?? "NODE_01";

  const motion =
    Boolean(sensorData?.motion ?? false);

  const vibration =
    Number(sensorData?.vibration ?? 0);

  const temperature =
    sensorData?.temperature ?? "--";

  const battery =
    Number(sensorData?.battery ?? 0);

  const timestamp =
    sensorData?.timestamp ?? null;

  const nodeHealth =
    sensorData?.node_health ?? "UNKNOWN";

  const powerSource =
    sensorData?.power_source ?? "SOLAR";

  // =========================================================
  // AI DETECTION VALUES
  // =========================================================

  const elephantDetected =
    Boolean(
      detectionData?.elephant_detected ?? false
    );

  const elephantCount =
    Number(
      detectionData?.elephant_count ?? 0
    );

  const elephantConfidence =
    Number(
      detectionData?.elephant_confidence ?? 0
    );

  const humanDetected =
    Boolean(
      detectionData?.human_detected ?? false
    );

  const humanCount =
    Number(
      detectionData?.human_count ?? 0
    );

  const humanSightings =
    Array.isArray(
      detectionData?.human_sightings
    )
      ? detectionData.human_sightings
      : [];

  const humanHistoryEvents =
    Array.isArray(
      humanHistoryData?.events
    )
      ? humanHistoryData.events
      : [];

  const humanSightingTotal =
    Number(
      humanHistoryData?.total_sightings ??
        humanHistoryEvents.length
    );

  const vehicleDetected =
    Boolean(
      detectionData?.vehicle_detected ?? false
    );

  const vehicleCount =
    Number(
      detectionData?.vehicle_count ?? 0
    );

  const elephantsList =
    Array.isArray(detectionData?.elephants)
      ? detectionData.elephants
      : [];

  // =========================================================
  // MOVEMENT / LOCATION
  // =========================================================

  const backendMovement =
    detectionData?.movement ??
    riskData?.movement ??
    "NO MOVEMENT";

  const movement = elephantDetected
    ? String(backendMovement).toUpperCase()
    : "NO MOVEMENT";

  const backendLocation =
    detectionData?.location ??
    "NO ELEPHANT";

  const location = elephantDetected
    ? String(backendLocation).toUpperCase()
    : "NO ELEPHANT";

  // =========================================================
  // LIVE MAP POSITION
  // =========================================================

  const rawX =
    Number(detectionData?.x_position ?? 0);

  const rawY =
    Number(detectionData?.y_position ?? 0);

  const xPosition =
    Math.max(0, Math.min(1, rawX));

  const yPosition =
    Math.max(0, Math.min(1, rawY));

  const mapPosition = {
    x: 10 + xPosition * 80,
    y: 10 + yPosition * 75,
  };

  // =========================================================
  // ELEPHANT MOVEMENT TRAIL
  // =========================================================

  useEffect(() => {
    if (!elephantDetected) {
      setTrail([]);
      return;
    }

    setTrail((prev) => {
      const last = prev[prev.length - 1];

      if (
        last &&
        Math.abs(last.x - mapPosition.x) < 1.5 &&
        Math.abs(last.y - mapPosition.y) < 1.5
      ) {
        return prev;
      }

      const next = [
        ...prev,
        {
          x: mapPosition.x,
          y: mapPosition.y,
        },
      ];

      return next.slice(-5);
    });

    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [
    elephantDetected,
    mapPosition.x,
    mapPosition.y,
  ]);

  // =========================================================
  // RISK DATA
  // =========================================================

  const riskScore =
    Number(riskData?.risk_score ?? 0);

  const riskLevel =
    String(
      riskData?.risk_level ?? "LOW"
    ).toUpperCase();

  const riskReasons =
    Array.isArray(riskData?.reasons)
      ? riskData.reasons
      : [];

  const recommendedAction =
    riskData?.recommended_action ??
    "NO ACTION REQUIRED";

  const explanation =
    riskData?.explanation ?? "";

  const safeRoute =
    riskData?.safe_route ?? "";

  const prediction =
    riskData?.prediction ?? null;

  const riskClass =
    riskLevel.toLowerCase();

  // =========================================================
  // ACTUATOR DATA
  // =========================================================

  const buzzer =
    Boolean(actuatorData?.buzzer ?? false);

  const led =
    Boolean(actuatorData?.led ?? false);

  const alert =
    Boolean(actuatorData?.alert ?? false);

  // =========================================================
  // ALERT DATA
  // =========================================================

  const alerts =
    Array.isArray(alertData?.events)
      ? alertData.events
      : [];

  const totalEvents =
    Number(
      alertData?.total_events ??
        alerts.length
    );

  const warningEvents =
    alerts.filter(
      (a) =>
        String(a?.mode ?? "")
          .toUpperCase() === "WARNING"
    ).length;

  const criticalEvents =
    alerts.filter(
      (a) =>
        String(a?.mode ?? "")
          .toUpperCase() === "CRITICAL"
    ).length;

  const normalEvents =
    alerts.filter(
      (a) =>
        String(a?.mode ?? "")
          .toUpperCase() === "NORMAL"
    ).length;

  // =========================================================
  // ANALYTICS DATA
  // =========================================================

  const historyEvents =
    Array.isArray(historyData?.events)
      ? historyData.events
      : [];

  const heatmapBins =
    Array.isArray(heatmapData?.bins)
      ? heatmapData.bins
      : [];

  const maxHeatCount =
    Math.max(
      1,
      ...heatmapBins.map(
        (b) => b.count
      )
    );

  // =========================================================
  // RENDER
  // =========================================================

  return (
    <div className="app">

      {/* HEADER */}
      <header className="header">
        <div>
          <h1>🐘 EleGuard AI</h1>
          <p>
            Intelligent Human–Elephant Conflict
            Prevention System
          </p>
        </div>

        <div className="header-right">

          {/* THEME TOGGLE */}
          <button
            className="theme-toggle-btn"
            onClick={toggleTheme}
            title="Toggle light/dark theme"
          >
            {theme === "dark"
              ? "🌙 Dark"
              : "☀️ Light"}
          </button>

          {/* SOUND TOGGLE */}
          <button
            className={`sound-toggle-btn ${
              soundEnabled ? "sound-on" : ""
            }`}
            onClick={enableSound}
            title="Enable critical alert beep sound"
          >
            {soundEnabled
              ? "🔊 Sound ON"
              : "🔈 Enable Alert Sound"}
          </button>

          {/* INPUT SOURCE TOGGLE */}
          <button
            className={`camera-toggle-btn ${
              cameraMode === "CAMERA" ? "camera-on" : ""
            }`}
            onClick={toggleCameraMode}
            disabled={cameraBusy}
            title="Switch between demo video and laptop camera"
          >
            {cameraBusy
              ? "⏳ Switching..."
              : cameraMode === "CAMERA"
                ? "📷 Camera ON"
                : "🎥 Video Mode"}
          </button>

          {/* DEMO MODE TOGGLE */}
          <button
            className={`camera-toggle-btn ${
              demoMode ? "camera-on" : ""
            }`}
            onClick={toggleDemoMode}
            title="Toggle built-in demo simulator (elephant movement + video)"
          >
            {demoMode ? "🎬 Demo ON" : "🎬 Demo OFF"}
          </button>

          <div
            className={`system-status ${
              offline ? "offline" : ""
            }`}
          >
            <span className="status-dot"></span>
            {offline
              ? "OFFLINE MODE - CACHED DATA"
              : "SYSTEM ONLINE"}
          </div>
        </div>
      </header>

      {error && (
        <div className="error">
          ⚠️ {error}
        </div>
      )}

      {/* CRITICAL ALERT BANNER */}
      {riskLevel === "CRITICAL" && (
        <div className="critical-banner">
          🔴 CRITICAL &nbsp;|&nbsp;

          {humanElephantConflict
            ? "👤 Human + 🐘 Elephant same zone"
            : "🐘 Elephant near village"}

          &nbsp;|&nbsp; 🚨 ALERT ACTIVE

          {soundEnabled ? (
            <span className="beep-indicator">
              🔊 BEEP BEEP BEEP
            </span>
          ) : (
            <span className="beep-indicator muted">
              🔈 Tap "Enable Alert Sound" above
              to hear beeps
            </span>
          )}
        </div>
      )}

      <main>

        {/* HUMAN + ELEPHANT CONFLICT */}
        {humanElephantConflict && (
          <div className="human-elephant-alert">
            🚨 <strong>IMMEDIATE DANGER:</strong>{" "}
            Human and elephant detected in the same
            zone ({location}). Take immediate safety
            precautions.
          </div>
        )}

        {/* =====================================================
            DASHBOARD
            ===================================================== */}
        <div className="dashboard">

          {/* 1. IOT NODE */}
          <section className="card node-card">
            <div className="card-title">
              <h2>📡 IoT Node</h2>

              <span
                className={
                  nodeHealth === "ONLINE"
                    ? "online"
                    : "node-offline"
                }
              >
                {nodeHealth}
              </span>
            </div>

            <h3>{nodeId}</h3>

            <p className="timestamp">
              Last update:{" "}
              {timestamp
                ? new Date(
                    timestamp
                  ).toLocaleTimeString()
                : "--"}
            </p>

            <p className="power-badge">
              ☀️ Power: {powerSource}
            </p>
          </section>

          {/* 2. MOTION */}
          <section className="card">
            <div className="sensor-icon">
              📳
            </div>

            <h3>Motion</h3>

            <div
              className={`sensor-value ${
                motion ? "danger" : "safe"
              }`}
            >
              {motion
                ? "DETECTED"
                : "NORMAL"}
            </div>

            <p>PIR Sensor</p>
          </section>

          {/* 3. VIBRATION */}
          <section className="card">
            <div className="sensor-icon">
              📊
            </div>

            <h3>Vibration</h3>

            <div className="big-value">
              {vibration}
            </div>

            <div className="progress">
              <div
                className="progress-bar"
                style={{
                  width: `${Math.min(
                    Math.max(
                      vibration,
                      0
                    ),
                    100
                  )}%`,
                }}
              ></div>
            </div>

            <p>Intensity: 0–100</p>
          </section>

          {/* 4. TEMPERATURE */}
          <section className="card">
            <div className="sensor-icon">
              🌡️
            </div>

            <h3>Temperature</h3>

            <div className="big-value">
              {temperature === "--"
                ? "--"
                : `${temperature}°C`}
            </div>

            <p>
              Environmental sensor
            </p>
          </section>

          {/* 5. BATTERY */}
          <section className="card">
            <div className="sensor-icon">
              🔋
            </div>

            <h3>Battery</h3>

            <div className="big-value">
              {battery}%
            </div>

            <div className="progress">
              <div
                className="progress-bar battery"
                style={{
                  width: `${Math.min(
                    Math.max(
                      battery,
                      0
                    ),
                    100
                  )}%`,
                }}
              ></div>
            </div>

            <p>
              Node power status
            </p>
          </section>

          {/* 6. AUTOMATED RESPONSE */}
          <section className="card actuator-card">
            <h2>
              ⚙️ Automated Response
            </h2>

            <div className="actuator">
              <span>🔊 Buzzer</span>

              <strong
                className={
                  buzzer
                    ? "active"
                    : "inactive"
                }
              >
                {buzzer
                  ? "ON"
                  : "OFF"}
              </strong>
            </div>

            <div className="actuator">
              <span>
                💡 Warning LED
              </span>

              <strong
                className={
                  led
                    ? "active"
                    : "inactive"
                }
              >
                {led
                  ? "ON"
                  : "OFF"}
              </strong>
            </div>

            <div className="actuator">
              <span>🚨 Alert</span>

              <strong
                className={
                  alert
                    ? "active"
                    : "inactive"
                }
              >
                {alert
                  ? "ACTIVE"
                  : "OFF"}
              </strong>
            </div>
          </section>

          {/* 7. AI DETECTION */}
          <section className="card feature-card">
            <h2>🐘 AI Detection</h2>

            <div
              className={`ai-status ${
                elephantDetected
                  ? "detected"
                  : "clear"
              }`}
            >
              {elephantDetected
                ? "🔴 ELEPHANT DETECTED"
                : "🟢 NO ELEPHANT"}
            </div>

            <div className="ai-info">

              <div>
                <span>
                  Confidence
                </span>

                <strong>
                  {elephantConfidence.toFixed(
                    2
                  )}
                  %
                </strong>
              </div>

              <div>
                <span>
                  Elephants
                </span>

                <strong>
                  {elephantCount}
                </strong>
              </div>

              <div>
                <span>
                  Humans
                </span>

                <strong>
                  {humanCount}
                </strong>
              </div>

              <div>
                <span>
                  Vehicles
                </span>

                <strong>
                  {vehicleCount}
                </strong>
              </div>

            </div>

            <p>
              🤖 AI Engine:{" "}
              <strong>
                ONLINE
              </strong>{" "}

              {vehicleDetected &&
                "· 🚗 Vehicle nearby"}

              {humanDetected &&
                "· 👤 Human nearby"}
            </p>

            {elephantsList.length > 1 && (
              <div className="elephant-list">

                {elephantsList.map(
                  (e, i) => (
                    <div
                      className="elephant-list-item"
                      key={e.id ?? i}
                    >
                      <span>
                        🐘 #{i + 1}
                      </span>

                      <span>
                        {e.movement}
                      </span>

                      <span>
                        {e.location}
                      </span>

                      <span>
                        {e.confidence}%
                      </span>
                    </div>
                  )
                )}

              </div>
            )}
          </section>

          {/* 8. HEC RISK */}
          <section className="card feature-card">
            <h2>🧠 HEC Risk</h2>

            <div
              className={`risk-score ${riskClass}`}
            >
              {riskScore}
            </div>

            <div
              className={`risk-level ${riskClass}`}
            >
              {riskLevel}
            </div>

            <div className="risk-reasons">

              {riskReasons.length > 0
                ? riskReasons.map(
                    (reason, i) => (
                      <div key={i}>
                        ⚠️ {reason}
                      </div>
                    )
                  )
                : (
                  <div>
                    ✅ No immediate threat
                  </div>
                )}

            </div>

            {elephantDetected && (
              <div className="risk-reasons">

                <div>
                  🧭 Movement:{" "}
                  <strong>
                    {movement}
                  </strong>
                </div>

                <div>
                  📍 Location:{" "}
                  <strong>
                    {location}
                  </strong>
                </div>

              </div>
            )}

            {explanation && (
              <div className="explanation-box">
                💡 {explanation}
              </div>
            )}

            <div className="risk-action">
              <span>
                ACTION
              </span>

              <strong>
                {recommendedAction}
              </strong>
            </div>
          </section>

          {/* 8.5 LIVE CAMERA FEED */}
          <section className="card feature-card video-feed-card">

            <div className="card-title">
              <h2>
                {cameraMode === "CAMERA"
                  ? "📷 Live Laptop Camera"
                  : "🎥 Live Video Feed"}
              </h2>

              <span className={`live-badge ${
                cameraMode === "CAMERA" ? "camera-live-badge" : ""
              }`}>
                <span className="live-dot"></span>
                {cameraMode === "CAMERA" ? "CAMERA" : "VIDEO"}
              </span>
            </div>

            <img
              src={`${API}/api/video-feed`}
              alt="Live YOLO detection feed"
              className="video-feed-img"
              onError={(e) => {
                e.target.style.display =
                  "none";
              }}
            />

            <p className="video-feed-caption">
              {cameraMode === "CAMERA"
                ? "Laptop webcam → YOLO → Backend → Dashboard. Live elephant, human and vehicle detection."
                : "Demo video → YOLO → Backend → Dashboard. Existing real-time detection feed."}
            </p>

            {cameraError && (
              <p className="camera-mode-error">⚠️ {cameraError}</p>
            )}

          </section>

          {/* 9. LIVE MAP */}
          <section className="card feature-card map-card">

            <h2>
              🗺️ Live Map
            </h2>

            <div className="live-map">

              <div className="forest-area">

                <div className="forest-label">
                  🌳 FOREST ZONE
                </div>

                <div className="tree tree-1">
                  🌲
                </div>

                <div className="tree tree-2">
                  🌳
                </div>

                <div className="tree tree-3">
                  🌲
                </div>

                <div className="tree tree-4">
                  🌳
                </div>

                {/* MOVEMENT TRAIL */}
                {trail.length > 1 && (
                  <svg
                    className="trail-svg"
                    viewBox="0 0 100 100"
                    preserveAspectRatio="none"
                  >
                    <polyline
                      className="trail-line"
                      points={trail
                        .map(
                          (p) =>
                            `${p.x},${p.y}`
                        )
                        .join(" ")}
                    />
                  </svg>
                )}

                {/* TRAIL ELEPHANTS */}
                {trail
                  .slice(0, -1)
                  .map((p, i) => (
                    <div
                      key={`trail-elephant-${i}`}
                      className="trail-elephant"
                      style={{
                        left: `${p.x}%`,
                        top: `${p.y}%`,
                        opacity:
                          0.25 +
                          (i /
                            Math.max(
                              1,
                              trail.length - 1
                            )) *
                            0.45,
                        fontSize: `${
                          13 + i * 3
                        }px`,
                      }}
                    >
                      🐘
                    </div>
                  ))}

                {/* HUMAN MARKERS */}
                {humanSightings.map(
                  (h, i) => {
                    const hx =
                      Math.max(
                        0,
                        Math.min(
                          1,
                          Number(
                            h.x_position ??
                              0
                          )
                        )
                      );

                    const hy =
                      Math.max(
                        0,
                        Math.min(
                          1,
                          Number(
                            h.y_position ??
                              0
                          )
                        )
                      );

                    const hpos = {
                      x: 10 + hx * 80,
                      y: 10 + hy * 75,
                    };

                    return (
                      <div
                        className={`human-marker ${
                          humanElephantConflict &&
                          String(
                            h.location
                          ).toUpperCase() ===
                            location
                            ? "conflict"
                            : ""
                        }`}
                        key={`human-${
                          h.id ?? i
                        }`}
                        style={{
                          left: `${hpos.x}%`,
                          top: `${hpos.y}%`,
                        }}
                        title={`Human #${
                          i + 1
                        } - Location: ${
                          h.location
                        }`}
                      >
                        👤
                      </div>
                    );
                  }
                )}

                {/* ELEPHANT MARKERS */}
                {elephantsList.length >
                0 ? (
                  elephantsList.map(
                    (e, i) => {

                      const ex =
                        Math.max(
                          0,
                          Math.min(
                            1,
                            Number(
                              e.x_position ??
                                0
                            )
                          )
                        );

                      const ey =
                        Math.max(
                          0,
                          Math.min(
                            1,
                            Number(
                              e.y_position ??
                                0
                            )
                          )
                        );

                      const pos = {
                        x: 10 + ex * 80,
                        y: 10 + ey * 75,
                      };

                      const isPrimary =
                        String(
                          e.id ?? ""
                        ) ===
                        String(
                          detectionData?.primary_elephant_id ??
                            ""
                        );

                      return (
                        <div
                          className={`elephant-marker ${
                            isPrimary
                              ? "primary"
                              : ""
                          }`}
                          key={
                            e.id ?? i
                          }
                          style={{
                            left: `${pos.x}%`,
                            top: `${pos.y}%`,
                          }}
                          title={`Elephant #${
                            i + 1
                          } - Movement: ${
                            e.movement
                          } | Location: ${
                            e.location
                          }`}
                        >
                          🐘
                        </div>
                      );
                    }
                  )
                ) : (
                  elephantDetected && (
                    <div
                      className="elephant-marker primary"
                      style={{
                        left: `${mapPosition.x}%`,
                        top: `${mapPosition.y}%`,
                      }}
                      title={`Movement: ${movement} | Location: ${location}`}
                    >
                      🐘
                    </div>
                  )
                )}

                {/* RISK ZONE */}
                {elephantDetected && (
                  <div
                    className="risk-zone"
                    style={{
                      left: `${Math.max(
                        5,
                        Math.min(
                          80,
                          mapPosition.x - 5
                        )
                      )}%`,
                      top: `${Math.max(
                        5,
                        Math.min(
                          80,
                          mapPosition.y - 8
                        )
                      )}%`,
                    }}
                  >
                    <span>🔴</span>
                    <small>
                      RISK ZONE
                    </small>
                  </div>
                )}

                {/* SAFE ZONE */}
                <div className="safe-zone">
                  <span>🟢</span>
                  <small>
                    SAFE ZONE
                  </small>
                </div>

              </div>

              <div className="village-area">
                🏘️ VILLAGE
              </div>

              <div className="node-marker">
                📡 {nodeId}
              </div>

            </div>

            <div className="map-status">

              <span>
                🐘 Elephant:{" "}
                <strong>
                  {elephantDetected
                    ? "DETECTED"
                    : "NOT DETECTED"}
                </strong>
              </span>

              <span>
                🧭 Movement:{" "}
                <strong>
                  {movement}
                </strong>
              </span>

              <span>
                📍 Location:{" "}
                <strong>
                  {location}
                </strong>
              </span>

              <span>
                🧠 Risk:{" "}
                <strong>
                  {riskLevel}
                </strong>
              </span>

              <span>
                👤 Humans:{" "}
                <strong>
                  {humanCount}
                </strong>
              </span>

            </div>

          </section>

          {/* 10. MOVEMENT PREDICTION */}
          <section className="card feature-card">

            <h2>
              🔮 Movement Prediction
            </h2>

            {prediction ? (
              <>
                <div className="prediction-trend">

                  {prediction.trend ===
                    "TOWARD_VILLAGE" &&
                    "📈 Heading toward village"}

                  {prediction.trend ===
                    "MOVING_AWAY" &&
                    "📉 Heading away from village"}

                  {prediction.trend ===
                    "STATIONARY" &&
                    "⏸️ Not moving"}

                  {prediction.trend ===
                    "NO_ELEPHANT" &&
                    "— No elephant to track"}

                  {prediction.trend ===
                    "INSUFFICIENT_DATA" &&
                    "⏳ Gathering data..."}

                </div>

                <div className="prediction-row">
                  <span>
                    Predicted zone (30s)
                  </span>

                  <strong>
                    {
                      prediction.predicted_zone_30s
                    }
                  </strong>
                </div>

                <div className="prediction-row">
                  <span>
                    ETA to village
                  </span>

                  <strong>
                    {prediction.eta_to_village_seconds !=
                    null
                      ? `${prediction.eta_to_village_seconds}s`
                      : "--"}
                  </strong>
                </div>
              </>
            ) : (
              <p>
                Waiting for movement
                data...
              </p>
            )}

          </section>

          {/* 11. SAFE ROUTE */}
          <section className="card feature-card">

            <h2>
              🛣️ Safe Route
            </h2>

            <p className="safe-route-text">
              {safeRoute ||
                "No route data yet."}
            </p>

            {riskData?.voice_alert && (
              <p className="voice-alert-text">
                🗣️ Voice alert active
                (Tamil)
              </p>
            )}

          </section>

          {/* 12. ALERT HISTORY */}
          <section className="card alert-history-card">

            <div className="alert-header">

              <h2>
                🚨 Alert History
              </h2>

              <div className="alert-header-right">

                <span
                  className={`sms-badge ${
                    smsData?.enabled
                      ? "sms-on"
                      : "sms-off"
                  }`}
                >
                  📧 Email:{" "}
                  {smsData?.enabled
                    ? `ON (${
                        smsData?.last_status ??
                        "READY"
                      })`
                    : "NOT CONFIGURED"}
                </span>

                <button
                  className="false-alarm-btn"
                  onClick={
                    reportFalseAlarm
                  }
                >
                  🚫 Mark False Alarm
                </button>

                <span className="event-count">
                  {totalEvents} Events
                </span>

              </div>

            </div>

            {alerts.length > 0 ? (
              <div className="alert-list">

                {alerts.map(
                  (item, index) => {

                    const mode =
                      String(
                        item?.mode ??
                          "NORMAL"
                      ).toLowerCase();

                    const upperMode =
                      String(
                        item?.mode ??
                          "NORMAL"
                      ).toUpperCase();

                    const targets =
                      Array.isArray(
                        item?.target
                      )
                        ? item.target
                        : [];

                    return (
                      <div
                        className={`alert-item ${mode}`}
                        key={
                          item?.timestamp ??
                          index
                        }
                      >

                        <div className="alert-time">
                          {item?.time ??
                            (item?.timestamp
                              ? new Date(
                                  item.timestamp
                                ).toLocaleTimeString()
                              : "--")}
                        </div>

                        <div className="alert-content">

                          <strong>

                            {upperMode ===
                              "CRITICAL" &&
                              "🔴 "}

                            {upperMode ===
                              "WARNING" &&
                              "🟠 "}

                            {upperMode ===
                              "NORMAL" &&
                              "🟢 "}

                            {upperMode ===
                              "FALSE_ALARM" &&
                              "🚫 "}

                            {upperMode}

                          </strong>

                          <p>
                            {item?.message ??
                              "No message"}
                          </p>

                          {targets.length >
                            0 && (
                            <p className="alert-targets">
                              📨 Notified:{" "}
                              {targets
                                .map(
                                  (t) =>
                                    t.replace(
                                      "_",
                                      " "
                                    )
                                )
                                .join(
                                  ", "
                                )}
                            </p>
                          )}

                        </div>

                        <div className="alert-score">
                          {item?.risk_score ??
                            0}
                        </div>

                      </div>
                    );
                  }
                )}

              </div>
            ) : (
              <div className="no-alerts">
                No alert events yet
              </div>
            )}

          </section>

          {/* 13. DETECTION HISTORY */}
          <section className="card history-card">

            <h2>
              📜 Detection History
            </h2>

            {historyEvents.length >
            0 ? (
              <div className="history-list">

                {historyEvents
                  .slice(-15)
                  .reverse()
                  .map((item, i) => (
                    <div
                      className="history-item"
                      key={
                        item.timestamp ??
                        i
                      }
                    >
                      <span className="history-time">
                        {item.timestamp
                          ? new Date(
                              item.timestamp
                            ).toLocaleTimeString()
                          : "--"}
                      </span>

                      <span>
                        {item.elephant_detected
                          ? "🐘"
                          : "—"}
                      </span>

                      <span>
                        {item.movement}
                      </span>

                      <span>
                        {item.location}
                      </span>
                    </div>
                  ))}

              </div>
            ) : (
              <div className="no-alerts">
                No detection history yet
              </div>
            )}

          </section>

          {/* 13.5 HUMAN SIGHTING HISTORY */}
          <section className="card human-history-card">

            <h2>
              👤 Human Sightings
            </h2>

            <div className="human-history-summary">

              <span>
                Current humans:{" "}
                <strong>
                  {humanCount}
                </strong>
              </span>

              <span>
                Total sightings:{" "}
                <strong>
                  {humanSightingTotal}
                </strong>
              </span>

            </div>

            {humanHistoryEvents.length >
            0 ? (
              <div className="history-list">

                {humanHistoryEvents
                  .slice(-10)
                  .reverse()
                  .map((item, i) => (
                    <div
                      className="history-item human-history-item"
                      key={`${
                        item.timestamp ??
                        "human"
                      }-${i}`}
                    >

                      <span className="history-time">
                        {item.timestamp
                          ? new Date(
                              item.timestamp
                            ).toLocaleTimeString()
                          : "--"}
                      </span>

                      <span>
                        👤
                      </span>

                      <span>
                        {item.location}
                      </span>

                      <span>
                        {item.confidence}%
                      </span>

                    </div>
                  ))}

              </div>
            ) : (
              <div className="no-alerts">
                No human sightings yet
              </div>
            )}

          </section>

          {/* 14. CONFLICT HEATMAP */}
          <section className="card heatmap-card">

            <h2>
              🔥 Conflict Heatmap
              (Forest → Village)
            </h2>

            <div className="heat-strip-row">

              {heatmapBins.map(
                (bin, i) => {

                  const intensity =
                    bin.count /
                    maxHeatCount;

                  return (
                    <div
                      key={i}
                      className="heat-strip-cell"
                      style={{
                        backgroundColor:
                          `rgba(239, 68, 68, ${
                            0.12 +
                            intensity *
                              0.78
                          })`,
                      }}
                      title={`${bin.range}: ${bin.count} detections`}
                    ></div>
                  );
                }
              )}

            </div>

            <div className="heat-strip-legend">
              <span>
                🌳 Forest
              </span>

              <div className="heat-legend-gradient"></div>

              <span>
                Village 🏘️
              </span>
            </div>

            <div className="heatmap-row">

              {heatmapBins.map(
                (bin, i) => (
                  <div
                    className="heatmap-col"
                    key={i}
                  >

                    <div
                      className="heatmap-bar"
                      style={{
                        height: `${
                          (bin.count /
                            maxHeatCount) *
                          100
                        }%`,
                      }}
                      title={`${bin.range}: ${bin.count} detections`}
                    ></div>

                    <span className="heatmap-label">
                      {bin.range}
                    </span>

                  </div>
                )
              )}

            </div>

          </section>

          {/* 15. EVENT SUMMARY */}
          <section className="card event-summary-card">

            <h2>
              📊 Event Summary &amp;
              Risk Statistics
            </h2>

            <div className="summary-grid">

              <div className="summary-box">
                <span>
                  Total Events
                </span>
                <strong>
                  {totalEvents}
                </strong>
              </div>

              <div className="summary-box warning-box">
                <span>
                  🟠 Warning
                </span>
                <strong>
                  {warningEvents}
                </strong>
              </div>

              <div className="summary-box critical-box">
                <span>
                  🔴 Critical
                </span>
                <strong>
                  {criticalEvents}
                </strong>
              </div>

              <div className="summary-box normal-box">
                <span>
                  🟢 Normal
                </span>
                <strong>
                  {normalEvents}
                </strong>
              </div>

              <div className="summary-box">
                <span>
                  Avg Risk
                </span>
                <strong>
                  {statsData?.avg_risk_score ??
                    0}
                </strong>
              </div>

              <div className="summary-box">
                <span>
                  Peak Risk Hour
                </span>
                <strong>
                  {statsData?.peak_risk_hour
                    ? `${statsData.peak_risk_hour}:00`
                    : "--"}
                </strong>
              </div>

              <div className="summary-box">
                <span>
                  🚫 False Alarms
                </span>
                <strong>
                  {statsData?.false_alarm_count ??
                    0}
                </strong>
              </div>

            </div>

          </section>

          {/* 16. COST & IMPACT */}
          <section className="card event-summary-card cost-card">

            <h2>
              💰 Cost &amp;
              Real-World Impact
            </h2>

            <div className="cost-grid">

              <div className="cost-box">
                <span>
                  IoT Sensor Node
                </span>

                <strong>
                  ₹3,500–4,500
                </strong>

                <small>
                  ESP32 + PIR +
                  vibration + temp +
                  solar + battery
                </small>
              </div>

              <div className="cost-box">
                <span>
                  AI Camera Node
                </span>

                <strong>
                  ₹8,000–12,000
                </strong>

                <small>
                  Camera + Raspberry Pi /
                  Jetson Nano running YOLO
                </small>
              </div>

              <div className="cost-box highlight">
                <span>
                  Per Monitoring Point
                </span>

                <strong>
                  ~₹15,000
                </strong>

                <small>
                  One-time cost,
                  solar powered,
                  no recurring wiring
                </small>
              </div>

              <div className="cost-box">
                <span>
                  vs. Manual Night Patrol
                </span>

                <strong>
                  Recurring ₹₹₹/month
                </strong>

                <small>
                  Limited coverage,
                  human fatigue,
                  no 24/7 guarantee
                </small>
              </div>

            </div>

            <p className="cost-note">
              📈 A single forest-corridor
              deployment (5–10 nodes)
              covers a full village boundary
              at a one-time cost comparable
              to ~1 month of manual patrol
              wages - then runs autonomously
              on solar power.
            </p>

          </section>

        </div>
        {/* ✅ CLOSED .dashboard */}

      </main>

      <footer>
        EleGuard AI • Prototype v2.0
      </footer>

    </div>
  );
}

export default App;