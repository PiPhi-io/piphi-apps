FROM python:3.12.12-slim-bookworm@sha256:593bd06efe90efa80dc4eee3948be7c0fde4134606dd40d8dd8dbcade98e669c AS builder

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 PDM_CHECK_UPDATE=false
WORKDIR /build
RUN pip install --no-cache-dir "pdm==2.29.7"
COPY pyproject.toml pdm.lock ./
RUN pdm export --prod --without-hashes --output /tmp/requirements.txt \
    && pip wheel --no-cache-dir --wheel-dir /wheels -r /tmp/requirements.txt
COPY src ./src
RUN pip wheel --no-cache-dir --no-deps --wheel-dir /wheels .

FROM python:3.12.12-slim-bookworm@sha256:593bd06efe90efa80dc4eee3948be7c0fde4134606dd40d8dd8dbcade98e669c

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIPHI_AUTOMATION_LEDGER_PATH=/var/lib/piphi/ble-gateway/automation-actions.sqlite3
RUN groupadd --gid 65532 piphi \
    && useradd --uid 65532 --gid 65532 --no-create-home --home-dir /nonexistent --shell /usr/sbin/nologin piphi \
    && install -d -o 65532 -g 65532 -m 0700 /var/lib/piphi/ble-gateway
COPY --from=builder /wheels /wheels
RUN pip install --no-cache-dir /wheels/* && rm -rf /wheels
USER 65532:65532
EXPOSE 4210
ENTRYPOINT ["piphi_ble_gateway_sidecar"]
