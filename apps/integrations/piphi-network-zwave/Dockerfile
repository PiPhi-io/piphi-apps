FROM python:3.12-slim@sha256:78387bc3881b8273120a12ebe6c1ab22b018ccc2c9adf565ae1ac9b536e184ea AS dependencies

ARG PDM_VERSION=2.29.7
WORKDIR /build
RUN pip install --no-cache-dir "pdm==${PDM_VERSION}"
COPY pyproject.toml pdm.lock ./
RUN pdm export --prod --without-hashes --output requirements.txt

FROM python:3.12-slim@sha256:78387bc3881b8273120a12ebe6c1ab22b018ccc2c9adf565ae1ac9b536e184ea

ARG APP_VERSION=0.3.0
LABEL org.opencontainers.image.title="PiPhi Network Z-Wave" \
      org.opencontainers.image.description="Homeowner-facing Z-Wave integration backed by the managed Z-Wave JS sidecar" \
      org.opencontainers.image.source="https://github.com/PiPhi-io/piphi-apps" \
      org.opencontainers.image.version="${APP_VERSION}"

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIPHI_ENV=production \
    PIPHI_ZWAVE_SIDECAR_URL=http://127.0.0.1:4211 \
    PIPHI_AUTOMATION_LEDGER_PATH=/app/data/automation-actions.sqlite3

WORKDIR /app
COPY --from=dependencies /build/requirements.txt /tmp/requirements.txt
COPY pyproject.toml ./
COPY src ./src
RUN pip install --no-cache-dir -r /tmp/requirements.txt \
    && pip install --no-cache-dir --no-deps . \
    && rm /tmp/requirements.txt \
    && useradd --create-home --uid 10001 piphi \
    && mkdir -p /app/data \
    && chown -R piphi:piphi /app/data

USER piphi
EXPOSE 4221
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
  CMD python -c "import os, urllib.request; urllib.request.urlopen('http://127.0.0.1:' + os.getenv('PORT', '4221') + '/health', timeout=3)"
CMD ["python", "-m", "piphi_network_zwave.main"]
