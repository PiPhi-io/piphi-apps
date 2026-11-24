FROM python:3.12-slim@sha256:5e2bdb1b0d542d5039cffb8181c65930093949194a65c365dfb1b0fe13a4fa5b AS requirements
WORKDIR /build
RUN python -m pip install --no-cache-dir "pdm==2.29.7"
COPY pyproject.toml pdm.lock ./
RUN pdm export --prod --output /requirements.txt

FROM python:3.12-slim@sha256:5e2bdb1b0d542d5039cffb8181c65930093949194a65c365dfb1b0fe13a4fa5b
ARG RELEASE_VERSION=0.1.6
ARG SOURCE_REVISION=unknown
ARG SOURCE_REPOSITORY=https://github.com/PiPhi-io/piphi-apps
LABEL org.opencontainers.image.source="${SOURCE_REPOSITORY}" \
      org.opencontainers.image.revision="${SOURCE_REVISION}" \
      org.opencontainers.image.version="${RELEASE_VERSION}"
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIPHI_AUTOMATION_LEDGER_PATH=/var/lib/piphi/automation-actions.sqlite3
WORKDIR /app
COPY --from=requirements /requirements.txt /tmp/requirements.txt
RUN python -m pip install --no-cache-dir --require-hashes -r /tmp/requirements.txt
COPY pyproject.toml README.md capability-catalog.json ./
COPY src ./src
RUN python -m pip install --no-cache-dir --no-deps . \
    && groupadd --system --gid 10001 piphi \
    && useradd --system --uid 10001 --gid piphi --home-dir /nonexistent --shell /usr/sbin/nologin piphi \
    && mkdir -p /var/lib/piphi \
    && chown piphi:piphi /var/lib/piphi \
    && rm -rf /tmp/requirements.txt /root/.cache
USER 10001:10001
VOLUME ["/var/lib/piphi"]
EXPOSE 8090
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD ["python", "-c", "import json, urllib.request; json.load(urllib.request.urlopen('http://127.0.0.1:8090/health', timeout=3))"]
CMD ["uvicorn", "piphi_network_kaiterra_api.main:app", "--host", "0.0.0.0", "--port", "8090", "--no-access-log"]
