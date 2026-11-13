FROM docker:27-cli@sha256:851f91d241214e7c6db86513b270d58776379aacc5eb9c4a87e5b47115e3065c AS docker-cli

FROM python:3.12-slim@sha256:5e2bdb1b0d542d5039cffb8181c65930093949194a65c365dfb1b0fe13a4fa5b AS dependencies
ARG PDM_VERSION=2.29.7
WORKDIR /build
RUN pip install --no-cache-dir "pdm==${PDM_VERSION}"
COPY pyproject.toml pdm.lock ./
RUN pdm export --prod --without-hashes --output requirements.txt

FROM python:3.12-slim@sha256:5e2bdb1b0d542d5039cffb8181c65930093949194a65c365dfb1b0fe13a4fa5b
ARG APP_VERSION=0.1.18
LABEL org.opencontainers.image.title="PiPhi Zigbee2MQTT Sidecar" \
      org.opencontainers.image.description="Managed Zigbee2MQTT bridge helper for PiPhi" \
      org.opencontainers.image.source="https://github.com/PiPhi-io/piphi-apps" \
      org.opencontainers.image.version="${APP_VERSION}"

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1
WORKDIR /app
COPY pyproject.toml ./
COPY src ./src
COPY --from=docker-cli /usr/local/bin/docker /usr/local/bin/docker
COPY --from=dependencies /build/requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt \
    && pip install --no-cache-dir --no-deps . \
    && rm /tmp/requirements.txt
EXPOSE 8720
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD python -c "import os, urllib.request; urllib.request.urlopen('http://127.0.0.1:' + os.getenv('PORT', '8720') + '/health', timeout=3)"
CMD ["python", "-m", "piphi_network_zigbee2mqtt.main"]
