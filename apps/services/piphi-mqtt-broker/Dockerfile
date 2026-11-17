FROM --platform=$BUILDPLATFORM node:20-alpine@sha256:fb4cd12c85ee03686f6af5362a0b0d56d50c58a04632e6c0fb8363f609372293 AS build

WORKDIR /app

COPY package.json package-lock.json tsconfig.json ./
COPY src ./src

RUN npm ci && npm run build && npm prune --omit=dev

FROM node:20-alpine@sha256:fb4cd12c85ee03686f6af5362a0b0d56d50c58a04632e6c0fb8363f609372293

ARG RELEASE_VERSION=0.3.2
ARG SOURCE_REVISION=unknown
ARG SOURCE_REPOSITORY=https://github.com/PiPhi-io/piphi-apps
LABEL org.opencontainers.image.title="PiPhi MQTT Broker" \
      org.opencontainers.image.description="Managed MQTT broker platform service for PiPhi" \
      org.opencontainers.image.source="${SOURCE_REPOSITORY}" \
      org.opencontainers.image.revision="${SOURCE_REVISION}" \
      org.opencontainers.image.version="${RELEASE_VERSION}"

WORKDIR /app

COPY docker ./docker
COPY package.json ./
COPY --from=build /app/dist ./dist
COPY --from=build /app/node_modules ./node_modules

RUN apk add --no-cache mosquitto mosquitto-clients openssl su-exec \
    && chmod +x /app/docker/entrypoint.sh /app/docker/credentials-admin.sh /app/docker/tls-admin.sh \
    && mkdir -p /mosquitto/config /mosquitto/data /mosquitto/log \
    && chown -R mosquitto:mosquitto /mosquitto/config /mosquitto/data /mosquitto/log

ENV MQTT_HOST=0.0.0.0 \
    MQTT_PORT=1883 \
    MQTT_ALLOW_ANONYMOUS=false \
    MQTT_ALLOW_PLAINTEXT=false \
    MQTT_PERSISTENCE=true \
    MQTT_PERSISTENCE_LOCATION=/mosquitto/data/ \
    MQTT_LOG_DEST=stdout \
    MQTT_TOPIC_PREFIX=piphi \
    MQTT_CONFIG_OUTPUT=/mosquitto/config/mosquitto.conf \
    MQTT_IDENTITY_ROOT=/mosquitto/config/identity

EXPOSE 1883

VOLUME ["/mosquitto/config", "/mosquitto/data", "/mosquitto/log"]

HEALTHCHECK --interval=30s --timeout=8s --start-period=10s --retries=3 CMD ["node", "/app/dist/src/healthcheck.js", "--readiness"]

ENTRYPOINT ["/app/docker/entrypoint.sh"]
