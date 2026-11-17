FROM python:3.12-slim
ARG RELEASE_VERSION=0.1.2
ARG SOURCE_REVISION=unknown
ARG SOURCE_REPOSITORY=https://github.com/PiPhi-io/piphi-apps
LABEL org.opencontainers.image.source="${SOURCE_REPOSITORY}" \
      org.opencontainers.image.revision="${SOURCE_REVISION}" \
      org.opencontainers.image.version="${RELEASE_VERSION}"
WORKDIR /app
COPY pyproject.toml ./
COPY src ./src
RUN pip install --no-cache-dir . \
    && groupadd --system --gid 10001 piphi \
    && useradd --system --uid 10001 --gid piphi --home-dir /nonexistent piphi \
    && mkdir -p /data/piphi \
    && chown -R piphi:piphi /data/piphi
ENV PIPHI_AUTOMATION_LEDGER_PATH=/data/piphi/automation-actions.sqlite3
VOLUME ["/data/piphi"]
EXPOSE 4218
USER piphi
CMD ["uvicorn", "piphi_network_mikrotik_router.main:app", "--host", "0.0.0.0", "--port", "4218"]
