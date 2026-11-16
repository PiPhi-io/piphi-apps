FROM python:3.12-slim@sha256:5e2bdb1b0d542d5039cffb8181c65930093949194a65c365dfb1b0fe13a4fa5b AS dependencies
ARG PDM_VERSION=2.29.7
WORKDIR /build
RUN pip install --no-cache-dir "pdm==${PDM_VERSION}"
COPY pyproject.toml pdm.lock ./
RUN pdm export --prod --without-hashes --output requirements.txt

FROM python:3.12-slim@sha256:5e2bdb1b0d542d5039cffb8181c65930093949194a65c365dfb1b0fe13a4fa5b
ARG APP_VERSION=0.1.24
LABEL org.opencontainers.image.title="PiPhi Zigbee2MQTT Sidecar" \
      org.opencontainers.image.description="Managed Zigbee2MQTT bridge helper for PiPhi" \
      org.opencontainers.image.source="https://github.com/PiPhi-io/piphi-apps" \
      org.opencontainers.image.version="${APP_VERSION}"

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1
WORKDIR /app
COPY pyproject.toml ./
COPY src ./src
COPY --from=dependencies /build/requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt \
    && pip install --no-cache-dir --no-deps . \
    && rm /tmp/requirements.txt \
    && groupadd --gid 1000 piphi \
    && useradd --uid 1000 --gid 1000 --home-dir /app --no-create-home piphi \
    && mkdir -p /app/data \
    && chown -R 1000:1000 /app/data
USER 1000:1000
EXPOSE 8720
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD python -c "import os, urllib.request; urllib.request.urlopen('http://127.0.0.1:' + os.getenv('PORT', '8720') + '/health', timeout=3)"
CMD ["python", "-m", "piphi_network_zigbee2mqtt.main"]
