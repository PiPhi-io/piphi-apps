FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    RUNTIME_INGEST_URL=http://127.0.0.1:8090/ingest/rtl433 \
    RADIO_BAND=433mhz \
    RTLSDR_DEVICE=auto \
    RECEIVER_GAIN=auto

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        ca-certificates \
        rtl-433 \
        rtl-sdr \
        tini \
        usbutils \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml README.md /app/
COPY src /app/src

RUN pip install --no-cache-dir .

ENTRYPOINT ["tini", "--"]
CMD ["python", "-m", "piphi_rtl433_bridge.service"]
