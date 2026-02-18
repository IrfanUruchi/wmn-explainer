FROM ollama/ollama:latest

RUN apt-get update && apt-get install -y --no-install-recommends \
    python3 python3-venv ca-certificates wget \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app

RUN python3 -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app.py /app/app.py
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

ENV CONFIG_FILE=/config/config.env
ENV PYTHONUNBUFFERED=1
ENV OLLAMA_URL=http://127.0.0.1:11434

EXPOSE 8000 11434
ENTRYPOINT ["/entrypoint.sh"]
