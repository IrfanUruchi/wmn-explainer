import json
import os
import time
import threading
from typing import Any, Dict

import requests
import paho.mqtt.client as mqtt
from fastapi import FastAPI
from pydantic import BaseModel

app = FastAPI(title="WMN Explainer", version="1.0")


def require(name: str, value: str) -> str:
    if value is None or str(value).strip() == "":
        raise SystemExit(f"[config] Missing required env var: {name}")
    return value


# MQTT
MQTT_BROKER = os.getenv("MQTT_BROKER", "").strip()
MQTT_PORT = int(os.getenv("MQTT_PORT", "8883"))
MQTT_TLS = os.getenv("MQTT_TLS", "1").lower() in ("1", "true", "yes")
MQTT_USERNAME = os.getenv("MQTT_USERNAME", "").strip()
MQTT_PASSWORD = os.getenv("MQTT_PASSWORD", "").strip()

IN_TOPIC = os.getenv("IN_TOPIC", "wmn/analysis/#").strip()
OUT_BASE = os.getenv("OUT_TOPIC_BASE", "wmn/explain").strip()
QOS = int(os.getenv("MQTT_QOS", "0"))

# Local Ollama 
OLLAMA_URL = os.getenv("OLLAMA_URL", "http://127.0.0.1:11434").strip()
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "llama3.2:3b").strip()

# Output controls
MIN_EXPLAIN_INTERVAL_SEC = int(os.getenv("MIN_EXPLAIN_INTERVAL_SEC", "30"))
SCORE_DELTA_TRIGGER = int(os.getenv("SCORE_DELTA_TRIGGER", "10"))
MAX_CHARS = int(os.getenv("MAX_CHARS", "700"))


SYSTEM_PROMPT = os.getenv(
    "SYSTEM_PROMPT",
    "You are a wireless/network troubleshooting assistant. "
    "Write concise plain technical English. "
    "Return exactly 4 bullets:\n"
    "- Summary\n"
    "- Likely cause\n"
    "- Impact\n"
    "- Actions\n"
    "No emojis, no marketing language, no special characters.",
).strip()


class ExplainRequest(BaseModel):
    analysis: Dict[str, Any]


class ExplainResponse(BaseModel):
    explanation: str


# device_id -> {t, score, sig}
_last_by_device: Dict[str, Dict[str, Any]] = {}


def normalize_text(s: str) -> str:
    """
    Avoid Windows/console mojibake (e.g., â¦) by removing common unicode punctuation.
    Keeps output ASCII-friendly for demos and logs.
    """
    return (
        s.replace("\u2026", "...") 
        .replace("\u2013", "-")  
        .replace("\u2014", "-")     
        .replace("\u2019", "'")     
        .replace("\u2018", "'")
        .replace("\u201c", '"')     
        .replace("\u201d", '"')
        .replace("\u00a0", " ") 
    )


def _alerts_signature(alerts: Any) -> str:
    if not isinstance(alerts, list):
        return ""
    parts = []
    for a in alerts:
        if isinstance(a, dict):
            parts.append(f"{a.get('type','')}/{a.get('severity','')}")
        else:
            parts.append(str(a))
    return "|".join(sorted(parts))


def _should_explain(device_id: str, score: Any, alerts: Any) -> bool:
    now = time.time()
    prev = _last_by_device.get(device_id)
    sig = _alerts_signature(alerts)

    if prev is None:
        _last_by_device[device_id] = {"t": now, "score": score, "sig": sig}
        return True

   
    try:
        prev_score = int(prev["score"]) if prev["score"] is not None else None
        cur_score = int(score) if score is not None else None
    except Exception:
        prev_score = None
        cur_score = None

    big_score_change = False
    if prev_score is not None and cur_score is not None:
        big_score_change = abs(cur_score - prev_score) >= SCORE_DELTA_TRIGGER

    alerts_changed = sig != prev["sig"]
    interval_ok = (now - float(prev["t"])) >= MIN_EXPLAIN_INTERVAL_SEC

    if interval_ok or big_score_change or alerts_changed:
        _last_by_device[device_id] = {"t": now, "score": score, "sig": sig}
        return True

    return False


def ollama_chat(prompt: str) -> str:
    url = f"{OLLAMA_URL.rstrip('/')}/api/chat"
    payload = {
        "model": OLLAMA_MODEL,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ],
        "stream": False,
    }
    r = requests.post(url, json=payload, timeout=90)
    r.raise_for_status()
    data = r.json()
    text = (data.get("message") or {}).get("content") or ""
    text = normalize_text(text.strip())

    if len(text) > MAX_CHARS:
        text = text[:MAX_CHARS].rstrip() + "..."
    return text


def build_prompt(msg: Dict[str, Any]) -> str:
    device = msg.get("device_id", "unknown")
    raw = msg.get("raw", {}) or {}
    analysis = msg.get("analysis", {}) or {}
    score = analysis.get("wireless_score_0_100")
    alerts = analysis.get("alerts") or []
    mobility = analysis.get("mobility_event")

    return (
        f"Device: {device}\n"
        f"Score (0-100): {score}\n"
        f"Raw: rssi_dbm={raw.get('rssi_dbm')}, latency_ms_avg={raw.get('latency_ms_avg')}, "
        f"jitter_ms={raw.get('jitter_ms')}, loss_pct={raw.get('packet_loss_pct')}\n"
        f"Alerts: {alerts}\n"
        f"Mobility event: {mobility}\n\n"
        "Explain based only on these measurements.\n"
        "Use the 4 bullet format requested.\n"
    )


def mqtt_worker() -> None:
    require("MQTT_BROKER", MQTT_BROKER)
    if (MQTT_USERNAME and not MQTT_PASSWORD) or (MQTT_PASSWORD and not MQTT_USERNAME):
        raise SystemExit("[config] Provide BOTH MQTT_USERNAME and MQTT_PASSWORD (or neither).")

    c = mqtt.Client()
    if MQTT_USERNAME and MQTT_PASSWORD:
        c.username_pw_set(MQTT_USERNAME, MQTT_PASSWORD)
    if MQTT_TLS:
        c.tls_set()

    def on_connect(_c, _u, _f, rc):
        print(f"[mqtt] on_connect rc={rc} connected={rc == 0}")
        if rc == 0:
            _c.subscribe(IN_TOPIC, qos=QOS)
            print(f"[mqtt] subscribed {IN_TOPIC}")

    def on_message(_c, _u, msg):
        try:
            payload = json.loads(msg.payload.decode("utf-8"))
        except Exception:
            print("[warn] invalid json on input")
            return

        device_id = payload.get("device_id") or "unknown"
        analysis = payload.get("analysis", {}) or {}
        score = analysis.get("wireless_score_0_100")
        alerts = analysis.get("alerts") or []

        if not _should_explain(device_id, score, alerts):
            return

        prompt = build_prompt(payload)
        try:
            explanation = ollama_chat(prompt)
        except Exception as e:
            print(f"[err] ollama call failed: {e}")
            return

        out_topic = f"{OUT_BASE}/{device_id}"
        out = {
            "device_id": device_id,
            "timestamp": int(time.time()),
            "source_topic": msg.topic,
            "explanation": explanation,
            "analysis": payload.get("analysis"),
            "raw": payload.get("raw"),
        }
        _c.publish(out_topic, json.dumps(out, separators=(",", ":")), qos=QOS)
        print(f"[pub] {out_topic} chars={len(explanation)}")

    c.on_connect = on_connect
    c.on_message = on_message

    c.reconnect_delay_set(min_delay=1, max_delay=30)
    c.connect(MQTT_BROKER, MQTT_PORT, keepalive=60)
    c.loop_forever()


@app.get("/")
def root():
    return {"status": "ok", "docs": "/docs"}


@app.on_event("startup")
def startup():
    t = threading.Thread(target=mqtt_worker, daemon=True)
    t.start()


@app.post("/explain", response_model=ExplainResponse)
def explain(req: ExplainRequest):
    prompt = build_prompt(req.analysis)
    text = ollama_chat(prompt)
    return ExplainResponse(explanation=text)
