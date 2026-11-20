FROM python:3.12-slim@sha256:5e2bdb1b0d542d5039cffb8181c65930093949194a65c365dfb1b0fe13a4fa5b AS requirements
WORKDIR /build
RUN python -m pip install --no-cache-dir "pdm==2.29.7"
COPY pyproject.toml pdm.lock ./
RUN pdm export --prod --output /requirements.txt

FROM python:3.12-slim@sha256:5e2bdb1b0d542d5039cffb8181c65930093949194a65c365dfb1b0fe13a4fa5b
ARG RELEASE_VERSION=0.1.3
ARG SOURCE_REVISION=unknown
ARG SOURCE_REPOSITORY=https://github.com/PiPhi-io/piphi-apps
LABEL org.opencontainers.image.source="${SOURCE_REPOSITORY}" \
      org.opencontainers.image.revision="${SOURCE_REVISION}" \
      org.opencontainers.image.version="${RELEASE_VERSION}"
WORKDIR /app
COPY --from=requirements /requirements.txt /tmp/requirements.txt
RUN python -m pip install --no-cache-dir --require-hashes -r /tmp/requirements.txt
COPY pyproject.toml ./
COPY src ./src
RUN python -m pip install --no-cache-dir --no-deps . \
    && groupadd --system --gid 10001 piphi \
    && useradd --system --uid 10001 --gid piphi --home-dir /nonexistent piphi \
    && mkdir -p /data/piphi \
    && chown -R piphi:piphi /data/piphi
ENV PIPHI_AUTOMATION_LEDGER_PATH=/data/piphi/automation-actions.sqlite3
VOLUME ["/data/piphi"]
EXPOSE 4218
USER piphi
CMD ["uvicorn", "piphi_network_mikrotik_router.main:app", "--host", "0.0.0.0", "--port", "4218"]
