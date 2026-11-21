FROM node:22-alpine@sha256:1314fb30ec37592d5845e5a160d522c0e680972aa534549940b8d73bde88481a AS widget-build
WORKDIR /widget
COPY widgets/steam-activity/package*.json ./
RUN npm ci
COPY widgets/steam-activity ./
COPY src/manifest.json /src/manifest.json
RUN npm test && npm run build && npm run validate && npm run conformance

FROM python:3.12-slim@sha256:5e2bdb1b0d542d5039cffb8181c65930093949194a65c365dfb1b0fe13a4fa5b AS requirements
WORKDIR /app
RUN pip install --no-cache-dir "pdm==2.29.7"
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
    PIPHI_WIDGET_DIR=/app/widgets
WORKDIR /app
COPY --from=requirements /requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir --require-hashes -r /tmp/requirements.txt
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --no-cache-dir --no-deps . \
    && groupadd --system --gid 10001 piphi \
    && useradd --system --uid 10001 --gid piphi --home-dir /app piphi \
    && chown -R piphi:piphi /app
COPY --from=widget-build --chown=10001:10001 /widget/dist ./widgets/dist
COPY --from=widget-build --chown=10001:10001 /widget/widget.manifest.json ./widgets/widget.manifest.json
USER 10001:10001
EXPOSE 8090
HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8090/health', timeout=2)"
CMD ["python", "-m", "piphi_network_steam.main"]
