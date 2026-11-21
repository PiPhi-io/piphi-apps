FROM python:3.12-slim@sha256:5e2bdb1b0d542d5039cffb8181c65930093949194a65c365dfb1b0fe13a4fa5b AS dependencies
WORKDIR /build
RUN python -m pip install --no-cache-dir "pdm==2.29.7"
COPY pyproject.toml pdm.lock ./
RUN pdm export --prod --output /requirements.txt

FROM python:3.12-slim@sha256:5e2bdb1b0d542d5039cffb8181c65930093949194a65c365dfb1b0fe13a4fa5b
ARG RELEASE_VERSION=0.2.1
ARG SOURCE_REVISION=unknown
ARG SOURCE_REPOSITORY=https://github.com/PiPhi-io/piphi-apps
LABEL org.opencontainers.image.source="${SOURCE_REPOSITORY}" \
      org.opencontainers.image.revision="${SOURCE_REVISION}" \
      org.opencontainers.image.version="${RELEASE_VERSION}"
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/integration/src \
    PIPHI_AUTOMATION_LEDGER_PATH=/var/lib/piphi/automation-actions.sqlite3 \
    RTL433_DISCOVERY_CACHE_PATH=/var/lib/piphi/discovery.json \
    PORT=8090
WORKDIR /integration
COPY --from=dependencies /requirements.txt /tmp/requirements.txt
RUN python -m pip install --no-cache-dir --require-hashes -r /tmp/requirements.txt \
    && groupadd --system --gid 10001 piphi \
    && useradd --system --uid 10001 --gid 10001 --home-dir /integration piphi \
    && mkdir -p /var/lib/piphi \
    && chown -R 10001:10001 /integration /var/lib/piphi
COPY --chown=10001:10001 src /integration/src
VOLUME ["/var/lib/piphi"]
EXPOSE 8090
USER 10001:10001
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD python -c "import json, urllib.request; json.load(urllib.request.urlopen('http://127.0.0.1:8090/health', timeout=3))"
CMD ["sh", "-c", "python -m uvicorn piphi_network_433mhz.app:app --host 0.0.0.0 --port ${PORT:-8090}"]
