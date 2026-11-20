FROM node:22-slim@sha256:e9f565d32859f0cbfb52125eafe8be39390f24dac302dc3cdf566e8ba3ab21ee AS widgets
WORKDIR /widgets
COPY widgets ./
RUN for widget in pfsense-overview pfsense-client-security; do \
      cd "/widgets/$widget" && npm ci --ignore-scripts && npm run build || exit 1; \
    done

FROM python:3.12-slim@sha256:5e2bdb1b0d542d5039cffb8181c65930093949194a65c365dfb1b0fe13a4fa5b AS requirements
WORKDIR /build
RUN python -m pip install --no-cache-dir "pdm==2.29.7"
COPY pyproject.toml pdm.lock ./
RUN pdm export --prod --output /requirements.txt

FROM python:3.12-slim@sha256:5e2bdb1b0d542d5039cffb8181c65930093949194a65c365dfb1b0fe13a4fa5b
ARG RELEASE_VERSION=0.1.11
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
COPY --from=widgets /widgets ./widgets
ENV PIPHI_AUTOMATION_LEDGER_PATH=/data/piphi/automation-actions.sqlite3
ENV PIPHI_WIDGET_DIR=/app/widgets
VOLUME ["/data/piphi"]
EXPOSE 8090
USER piphi
CMD ["uvicorn", "piphi_network_pfsense.main:app", "--host", "0.0.0.0", "--port", "8090"]
