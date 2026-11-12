FROM python:3.12-slim

ARG RELEASE_VERSION=0.0.0-unqualified
ARG SOURCE_REVISION=0000000000000000000000000000000000000000
ARG SOURCE_REPOSITORY=https://github.com/PiPhi-io/piphi_network_tuya
ARG MANIFEST_SHA256=unqualified
ARG BEHAVIORS_SHA256=unqualified

LABEL org.opencontainers.image.version="${RELEASE_VERSION}" \
    org.opencontainers.image.revision="${SOURCE_REVISION}" \
    org.opencontainers.image.source="${SOURCE_REPOSITORY}" \
    io.piphi.manifest.sha256="${MANIFEST_SHA256}" \
    io.piphi.behaviors.sha256="${BEHAVIORS_SHA256}"

WORKDIR /app

ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app/src
ENV PIPHI_RUNTIME_PORT=4191
ENV PIPHI_AUTOMATION_LEDGER_PATH=/var/lib/piphi/automation-actions.sqlite3

COPY pyproject.toml README.md ./
COPY src ./src

RUN pip install --no-cache-dir . \
    && adduser --disabled-password --gecos "" --uid 10001 piphi \
    && mkdir -p /var/lib/piphi \
    && chown piphi:piphi /var/lib/piphi \
    && chown -R piphi:piphi /app

USER piphi

VOLUME ["/var/lib/piphi"]

EXPOSE 4191

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD python -c "import os, sys, urllib.request; port = os.getenv('PIPHI_RUNTIME_PORT', '4191'); urllib.request.urlopen('http://127.0.0.1:' + port + '/health', timeout=3); sys.exit(0)"

CMD ["python", "-m", "piphi_network_tuya.main"]
