FROM node:22-slim AS widgets
WORKDIR /widgets
COPY widgets ./
RUN for widget in pfsense-overview pfsense-client-security; do \
      cd "/widgets/$widget" && npm ci --ignore-scripts && npm run build || exit 1; \
    done

FROM python:3.12-slim
ARG RELEASE_VERSION=0.1.10
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
COPY --from=widgets /widgets ./widgets
ENV PIPHI_AUTOMATION_LEDGER_PATH=/data/piphi/automation-actions.sqlite3
ENV PIPHI_WIDGET_DIR=/app/widgets
VOLUME ["/data/piphi"]
EXPOSE 8090
USER piphi
CMD ["uvicorn", "piphi_network_pfsense.main:app", "--host", "0.0.0.0", "--port", "8090"]
