FROM python:3.12-slim AS dependencies

WORKDIR /build

COPY pyproject.toml pdm.lock /build/

RUN python -m pip install --no-cache-dir "pdm==2.29.7" \
    && pdm export --prod --without-hashes --output /tmp/requirements.txt \
    && python -m pip wheel --no-cache-dir --wheel-dir /wheels -r /tmp/requirements.txt

FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/integration/src \
    PIPHI_AUTOMATION_LEDGER_PATH=/tmp/piphi-network-433mhz-actions.sqlite3 \
    RTL433_DISCOVERY_CACHE_PATH=/tmp/piphi-network-433mhz-discovery.json \
    PORT=8090

WORKDIR /integration

RUN addgroup --system piphi && adduser --system --ingroup piphi --home /nonexistent piphi

COPY --from=dependencies /wheels /wheels
RUN python -m pip install --no-cache-dir --no-index /wheels/* \
    && rm -rf /wheels

COPY src /integration/src

EXPOSE 8090

USER piphi

CMD ["sh", "-c", "python -m uvicorn piphi_network_433mhz.app:app --host 0.0.0.0 --port ${PORT:-8090}"]
