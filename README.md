# WMN Explainer

The **WMN Explainer** is a fog-layer service that generates short, human-readable explanations for wireless network conditions.
It consumes analytics results via MQTT, produces concise explanations using a local language model runtime, and republishes the results for visualization and monitoring.

This component is part of a modular **Wireless and Mobile Networks (WMN)** system designed around edge, fog, and observability layers.

---

## Role in the System

The explainer runs at the **fog layer** and focuses on interpretation rather than measurement or scoring.

High-level flow:

```
Edge device → wmn-collector → MQTT → wmn-analyzer → MQTT → wmn-explainer
                                                     ↓
                                               Explanations
```

* **wmn-collector**: collects raw network metrics at the edge
* **wmn-analyzer**: computes scores and detects conditions
* **wmn-explainer**: explains the results in plain language

---

## What This Service Does

* Subscribes to MQTT analytics topics (`wmn/analysis/#`)
* Generates short explanations describing:

  * current network quality
  * likely causes
  * expected user impact
  * suggested actions
* Publishes explanations to MQTT (`wmn/explain/<device_id>`)
* Exposes an HTTP API for testing and dashboard integration

The language model is **selected at runtime** and cached locally.

---

## Runtime Model Selection

This image does **not** bundle a language model.
The model is downloaded on first run and stored in a Docker volume.

This allows deployment on heterogeneous fog nodes with different hardware capabilities.

Example guidance:

* CPU / low memory: `phi3:mini`
* ~6–8 GB VRAM: `llama3.2:3b`
* Higher VRAM: larger models may be used if available

The model can be specified via environment variable or during interactive setup.

---

## Docker Image

**Docker Hub**

* `irfanuruchi/wmn-explainer:latest`
* `irfanuruchi/wmn-explainer:1.0`

The image targets standard x86_64 fog nodes. ARM64 support can be added when required.

---

## Running the Service

### CPU-only

```bash
docker run -it --name wmn-explainer \
  --restart unless-stopped \
  -p 8000:8000 \
  -v wmn_explainer_config:/config \
  -v ollama_models:/root/.ollama \
  -e OLLAMA_MODEL=phi3:mini \
  irfanuruchi/wmn-explainer:latest
```

### NVIDIA GPU (optional)

```bash
docker run -it --name wmn-explainer \
  --restart unless-stopped \
  --gpus all \
  -p 8000:8000 \
  -v wmn_explainer_config:/config \
  -v ollama_models:/root/.ollama \
  -e OLLAMA_MODEL=llama3.2:3b \
  irfanuruchi/wmn-explainer:latest
```

On first run, the container prompts for MQTT configuration and saves it in `/config/config.env`.

---

## HTTP API

The service exposes a small HTTP API for testing and dashboard integration.

* `GET /` – service status
* `GET /docs` – OpenAPI / Swagger UI
* `POST /explain` – generate an explanation from an analysis payload

The API is intended for demos and dashboards rather than high-rate ingestion.

---

## Configuration

Configuration is stored persistently in a Docker volume:

```
/config/config.env
```

To reset configuration:

```bash
docker rm -f wmn-explainer
docker volume rm wmn_explainer_config
```

---

## Related Repositories (GitHub)

This repository is part of a multi-component system. Related GitHub repositories include:

* **wmn-collector**
  Edge-side network metrics collection
  *https://github.com/IrfanUruchi/wmn-collector*

* **wmn-analyzer**
  Fog-layer analytics and scoring service
  *https://github.com/IrfanUruchi/wmn-analyzer*

* **wmn-explainer** (this repository)
  Fog-layer explanation service

Additional repositories may be added as the project evolves.

---

## Related Docker Images

* **wmn-collector**
  `[irfanuruchi/wmn-collector](https://hub.docker.com/r/irfanuruchi/wmn-collector)`

* **wmn-analyzer**
  `[irfanuruchi/wmn-analyzer](https://hub.docker.com/r/irfanuruchi/wmn-analyzer)`

* **wmn-explainer**
  `[irfanuruchi/wmn-explainer](https://hub.docker.com/r/irfanuruchi/wmn-explainer)`

---

## Notes

* The explainer is intentionally decoupled from visualization tools.
* Dashboards (e.g. Grafana or Streamlit) consume explanation outputs rather than running language models directly.
* This separation simplifies deployment and aligns with fog computing principles.
