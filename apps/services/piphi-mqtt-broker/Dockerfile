FROM --platform=$BUILDPLATFORM node:20-alpine@sha256:fb4cd12c85ee03686f6af5362a0b0d56d50c58a04632e6c0fb8363f609372293 AS build

WORKDIR /app

COPY package.json package-lock.json tsconfig.json ./
COPY src ./src

RUN npm ci && npm run build && npm prune --omit=dev

FROM node:20-alpine@sha256:fb4cd12c85ee03686f6af5362a0b0d56d50c58a04632e6c0fb8363f609372293

ARG APP_VERSION=0.1.7
LABEL org.opencontainers.image.title="PiPhi MQTT Broker" \
      org.opencontainers.image.description="Managed MQTT broker platform service for PiPhi" \
      org.opencontainers.image.source="https://github.com/PiPhi-io/piphi-apps" \
      org.opencontainers.image.version="${APP_VERSION}"

WORKDIR /app

COPY docker ./docker
COPY package.json ./
COPY --from=build /app/dist ./dist
COPY --from=build /app/node_modules ./node_modules

RUN apk add --no-cache mosquitto mosquitto-clients \
    && chmod +x /app/docker/entrypoint.sh \
    && mkdir -p /mosquitto/config /mosquitto/data /mosquitto/log \
    && chown -R mosquitto:mosquitto /mosquitto/config /mosquitto/data /mosquitto/log

ENV MQTT_HOST=0.0.0.0 \
    MQTT_PORT=1883 \
    MQTT_ALLOW_ANONYMOUS=false \
    MQTT_PERSISTENCE=true \
    MQTT_PERSISTENCE_LOCATION=/mosquitto/data/ \
    MQTT_LOG_DEST=stdout \
    MQTT_TOPIC_PREFIX=piphi \
    MQTT_CONFIG_OUTPUT=/mosquitto/config/mosquitto.conf \
    MQTT_PASSWORD_FILE=/mosquitto/config/passwordfile

EXPOSE 1883

VOLUME ["/mosquitto/config", "/mosquitto/data", "/mosquitto/log"]

ENTRYPOINT ["/app/docker/entrypoint.sh"]
