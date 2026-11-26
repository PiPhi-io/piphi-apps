FROM --platform=$BUILDPLATFORM node:20-alpine@sha256:fb4cd12c85ee03686f6af5362a0b0d56d50c58a04632e6c0fb8363f609372293 AS build

WORKDIR /app

COPY package.json package-lock.json tsconfig.json ./
COPY src ./src

RUN npm ci && npm run build && npm prune --omit=dev

FROM node:20-alpine@sha256:fb4cd12c85ee03686f6af5362a0b0d56d50c58a04632e6c0fb8363f609372293 AS node-runtime

ARG TARGETARCH
RUN node_arch="$(node -p process.arch)" \
    && case "${TARGETARCH}:${node_arch}" in amd64:x64|arm64:arm64) ;; *) exit 1 ;; esac

FROM alpine:3.23@sha256:469c9ea410b9215eaee7976ba6c0639039b444be8e5d638f7abbada189971eb2

ARG RELEASE_VERSION=0.4.2
ARG SOURCE_REVISION=unknown
ARG SOURCE_REPOSITORY=https://github.com/PiPhi-io/piphi-apps
ARG MOSQUITTO_VERSION=2.0.22-r0
ARG OPENSSL_VERSION=3.5.9-r1
ARG SU_EXEC_VERSION=0.3-r0
ARG LIBSTDCXX_VERSION=15.2.0-r2
LABEL org.opencontainers.image.title="PiPhi MQTT Broker" \
      org.opencontainers.image.description="Managed MQTT broker platform service for PiPhi" \
      org.opencontainers.image.source="${SOURCE_REPOSITORY}" \
      org.opencontainers.image.revision="${SOURCE_REVISION}" \
      org.opencontainers.image.version="${RELEASE_VERSION}" \
      io.piphi.runtime.mosquitto.version="${MOSQUITTO_VERSION}" \
      io.piphi.runtime.openssl.version="${OPENSSL_VERSION}"

WORKDIR /app

COPY docker ./docker
COPY package.json ./
COPY --from=node-runtime /usr/local/bin/node /usr/local/bin/node
COPY --from=build /app/dist ./dist
COPY --from=build /app/node_modules ./node_modules

RUN apk add --no-cache \
      "mosquitto=${MOSQUITTO_VERSION}" \
      "mosquitto-clients=${MOSQUITTO_VERSION}" \
      "openssl=${OPENSSL_VERSION}" \
      "su-exec=${SU_EXEC_VERSION}" \
      "libstdc++=${LIBSTDCXX_VERSION}" \
    && chmod +x /app/docker/entrypoint.sh /app/docker/credentials-admin.sh /app/docker/tls-admin.sh /app/docker/storage-admin.sh \
    && mkdir -p /mosquitto/config /mosquitto/data /mosquitto/log \
    && chown -R mosquitto:mosquitto /mosquitto/config /mosquitto/data /mosquitto/log \
    && node --version

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
