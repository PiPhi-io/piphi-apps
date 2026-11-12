FROM python:3.12-slim AS builder

ENV PIP_NO_CACHE_DIR=1

WORKDIR /build

RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential git \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml README.md /build/
COPY src /build/src

RUN python -m pip install --upgrade pip \
    && python -m pip install --prefix=/install '.[hardware]'

FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/src \
    PIP_NO_CACHE_DIR=1 \
    PIPHI_I2C_PORT=3674 \
    PIPHI_AUTOMATION_LEDGER_PATH=/.piphinetwork/automation-actions.sqlite3

WORKDIR /app

COPY --from=builder /install /usr/local
COPY src /app/src

RUN mkdir -p /.piphinetwork

VOLUME ["/.piphinetwork"]
EXPOSE 3674

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD python -c "import json, urllib.request; json.load(urllib.request.urlopen('http://127.0.0.1:3674/health', timeout=3))" || exit 1

CMD ["python", "-m", "piphi_network_i2c.main"]
