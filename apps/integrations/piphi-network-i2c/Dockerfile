FROM python:3.12-slim@sha256:5e2bdb1b0d542d5039cffb8181c65930093949194a65c365dfb1b0fe13a4fa5b AS builder

ENV PIP_NO_CACHE_DIR=1

WORKDIR /build

COPY pyproject.toml pdm.lock README.md /build/
COPY src /build/src

RUN python -m pip install 'pdm==2.26.7' \
    && pdm export --prod -G hardware --output /tmp/requirements.txt \
    && python -m pip install --ignore-installed --prefix=/install --require-hashes -r /tmp/requirements.txt \
    && python -m pip install --prefix=/install --no-deps .

FROM python:3.12-slim@sha256:5e2bdb1b0d542d5039cffb8181c65930093949194a65c365dfb1b0fe13a4fa5b

ARG RELEASE_VERSION=0.1.6
ARG SOURCE_REVISION=unknown
ARG SOURCE_REPOSITORY=https://github.com/PiPhi-io/piphi-apps
LABEL org.opencontainers.image.source="${SOURCE_REPOSITORY}" \
      org.opencontainers.image.revision="${SOURCE_REVISION}" \
      org.opencontainers.image.version="${RELEASE_VERSION}"

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/src \
    PIP_NO_CACHE_DIR=1 \
    PIPHI_I2C_PORT=3674 \
    PIPHI_AUTOMATION_LEDGER_PATH=/.piphinetwork/automation-actions.sqlite3

WORKDIR /app

COPY --from=builder /install /usr/local
COPY src /app/src

RUN groupadd --system piphi && useradd --system --gid piphi --home-dir /nonexistent piphi \
    && mkdir -p /.piphinetwork \
    && chown piphi:piphi /.piphinetwork

VOLUME ["/.piphinetwork"]
EXPOSE 3674

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD python -c "import json, urllib.request; json.load(urllib.request.urlopen('http://127.0.0.1:3674/health', timeout=3))" || exit 1

USER piphi

CMD ["python", "-m", "piphi_network_i2c.main"]
