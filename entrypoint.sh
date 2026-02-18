#!/usr/bin/env sh
set -eu

CONFIG_FILE="${CONFIG_FILE:-/config/config.env}"
mkdir -p "$(dirname "$CONFIG_FILE")"

has_tty() { [ -t 0 ] && [ -t 1 ]; }

# GPU detection (native Linux NVIDIA uses /dev/nvidia*, WSL uses /dev/dxg)
if [ -e /dev/nvidia0 ] || [ -e /dev/nvidiactl ]; then
  echo "[gpu] NVIDIA device files present (/dev/nvidia*)"
elif [ -e /dev/dxg ]; then
  echo "[gpu] WSL GPU device present (/dev/dxg)"
elif [ -n "${NVIDIA_VISIBLE_DEVICES:-}" ] && [ "${NVIDIA_VISIBLE_DEVICES}" != "void" ]; then
  echo "[gpu] NVIDIA_VISIBLE_DEVICES=${NVIDIA_VISIBLE_DEVICES} (GPU requested)"
else
  echo "[gpu] No GPU device detected (CPU mode)"
fi

# First-run
if [ -f "$CONFIG_FILE" ]; then
  echo "Loading config: $CONFIG_FILE"
  # shellcheck disable=SC1090
  . "$CONFIG_FILE"
else
  if has_tty; then
    echo "=== WMN Explainer first-run setup ==="
    printf "MQTT broker host (required): "; read -r MQTT_BROKER
    printf "MQTT port [8883]: "; read -r MQTT_PORT; MQTT_PORT="${MQTT_PORT:-8883}"
    printf "Use TLS? [1]: "; read -r MQTT_TLS; MQTT_TLS="${MQTT_TLS:-1}"
    printf "MQTT username (empty if none): "; read -r MQTT_USERNAME
    printf "MQTT password (empty if none): "; stty -echo; read MQTT_PASSWORD; stty echo; echo ""
    printf "Subscribe topic [wmn/analysis/#]: "; read -r IN_TOPIC; IN_TOPIC="${IN_TOPIC:-wmn/analysis/#}"
    printf "Publish base [wmn/explain]: "; read -r OUT_TOPIC_BASE; OUT_TOPIC_BASE="${OUT_TOPIC_BASE:-wmn/explain}"
    printf "Ollama model [llama3.2:3b]: "; read -r OLLAMA_MODEL; OLLAMA_MODEL="${OLLAMA_MODEL:-llama3.2:3b}"

    cat > "$CONFIG_FILE" <<EOF
MQTT_BROKER=$MQTT_BROKER
MQTT_PORT=$MQTT_PORT
MQTT_TLS=$MQTT_TLS
MQTT_USERNAME=$MQTT_USERNAME
MQTT_PASSWORD=$MQTT_PASSWORD
IN_TOPIC=$IN_TOPIC
OUT_TOPIC_BASE=$OUT_TOPIC_BASE
OLLAMA_MODEL=$OLLAMA_MODEL
EOF
    echo "Saved $CONFIG_FILE"
  else
    echo "[ERROR] No config at $CONFIG_FILE and no TTY available."
    echo "Run once interactively:"
    echo "  docker run -it --rm -v wmn_explainer_config:/config -v ollama_models:/root/.ollama <image>"
    exit 1
  fi
fi

export MQTT_BROKER MQTT_PORT MQTT_TLS MQTT_USERNAME MQTT_PASSWORD IN_TOPIC OUT_TOPIC_BASE OLLAMA_MODEL
export OLLAMA_URL="${OLLAMA_URL:-http://127.0.0.1:11434}"

echo "[ollama] starting server..."
ollama serve >/var/log/ollama.log 2>&1 &

echo "[ollama] waiting for readiness..."
for i in $(seq 1 60); do
  if wget -qO- http://127.0.0.1:11434/api/tags >/dev/null 2>&1; then
    echo "[ollama] ready"
    break
  fi
  sleep 1
done

# Pull model if not present stored in volueme 
echo "[ollama] ensuring model is available: ${OLLAMA_MODEL}"
if ! ollama list | awk '{print $1}' | grep -qx "${OLLAMA_MODEL}"; then
  echo "[ollama] downloading model (first run only)..."
  ollama pull "${OLLAMA_MODEL}"
else
  echo "[ollama] model already present"
fi

exec uvicorn app:app --host 0.0.0.0 --port 8000
