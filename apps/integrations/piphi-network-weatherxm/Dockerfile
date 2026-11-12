FROM python:3.12-slim

ARG RELEASE_VERSION=0.0.0-unqualified
ARG SOURCE_REVISION=0000000000000000000000000000000000000000
ARG SOURCE_REPOSITORY=https://github.com/PiPhi-io/piphi_network_weatherxm
ARG MANIFEST_SHA256=unqualified
ARG BEHAVIORS_SHA256=unqualified

LABEL org.opencontainers.image.version="${RELEASE_VERSION}" \
    org.opencontainers.image.revision="${SOURCE_REVISION}" \
    org.opencontainers.image.source="${SOURCE_REPOSITORY}" \
    io.piphi.manifest.sha256="${MANIFEST_SHA256}" \
    io.piphi.behaviors.sha256="${BEHAVIORS_SHA256}"

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONPATH=/app/src \
    PIPHI_AUTOMATION_LEDGER_PATH=/var/lib/piphi/automation-actions.sqlite3

WORKDIR /app
RUN groupadd --system --gid 10001 piphi \
    && useradd --system --uid 10001 --gid piphi --home-dir /nonexistent --shell /usr/sbin/nologin piphi \
    && mkdir -p /var/lib/piphi \
    && chown piphi:piphi /var/lib/piphi
COPY pyproject.toml ./
COPY src ./src
RUN pip install --no-cache-dir .
USER piphi
VOLUME ["/var/lib/piphi"]
EXPOSE 8090
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD python -c "import json, urllib.request; json.load(urllib.request.urlopen('http://127.0.0.1:8090/health', timeout=3))" || exit 1
CMD ["uvicorn", "piphi_network_weatherxm.main:app", "--host", "0.0.0.0", "--port", "8090"]
