FROM node:22-slim AS widgets
WORKDIR /widgets
COPY widgets ./
RUN for widget in sense-energy-flow sense-device-breakdown; do \
      cd "/widgets/$widget" && npm ci --ignore-scripts && npm run build || exit 1; \
    done

FROM python:3.12-slim AS python-deps
WORKDIR /build
COPY pyproject.toml pdm.lock ./
COPY src ./src
RUN pip install --no-cache-dir "pdm==2.29.7" \
    && pdm export --prod --format requirements --output /tmp/requirements.txt \
    && pip wheel --no-cache-dir --require-hashes --requirement /tmp/requirements.txt --wheel-dir /wheels \
    && pip wheel --no-cache-dir --no-deps . --wheel-dir /wheels

FROM python:3.12-slim
ARG RELEASE_VERSION=0.0.0-dev
ARG SOURCE_REVISION=unknown
ARG SOURCE_REPOSITORY=https://github.com/PiPhi-io/piphi-apps
ARG MANIFEST_SHA256=unknown
ARG BEHAVIORS_SHA256=unknown
WORKDIR /app
RUN groupadd --system --gid 10001 piphi \
    && useradd --system --uid 10001 --gid piphi --home-dir /nonexistent --shell /usr/sbin/nologin piphi \
    && mkdir -p /var/lib/piphi \
    && chown piphi:piphi /var/lib/piphi
COPY --from=python-deps /wheels /wheels
RUN pip install --no-cache-dir --no-index --find-links=/wheels piphi-network-sense \
    && rm -rf /wheels
COPY --from=widgets /widgets ./widgets
ENV PIPHI_WIDGET_DIR=/app/widgets
ENV PIPHI_AUTOMATION_LEDGER_PATH=/var/lib/piphi/automation-actions.sqlite3
ENV PIPHI_SENSE_SESSION_STORE=/var/lib/piphi/sense-session.json
ENV PYTHONDONTWRITEBYTECODE=1
ENV HOME=/tmp
LABEL org.opencontainers.image.title="PiPhi Network Sense" \
      org.opencontainers.image.source="${SOURCE_REPOSITORY}" \
      org.opencontainers.image.version="${RELEASE_VERSION}" \
      org.opencontainers.image.revision="${SOURCE_REVISION}" \
      io.piphi.manifest.sha256="${MANIFEST_SHA256}" \
      io.piphi.behaviors.sha256="${BEHAVIORS_SHA256}"
VOLUME ["/var/lib/piphi"]
EXPOSE 8090
USER piphi
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD python -c "import json, urllib.request; json.load(urllib.request.urlopen('http://127.0.0.1:8090/health', timeout=3))" || exit 1
CMD ["uvicorn", "piphi_network_sense.main:app", "--host", "0.0.0.0", "--port", "8090"]
