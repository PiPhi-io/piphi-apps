# TypeScript output is architecture-neutral and serialport ships both glibc and
# musl prebuilds for every supported architecture. Run npm/Node on the native
# builder platform so arm64 publication never executes Node through QEMU.
FROM --platform=$BUILDPLATFORM node:22-alpine@sha256:1314fb30ec37592d5845e5a160d522c0e680972aa534549940b8d73bde88481a AS build
WORKDIR /app
RUN apk add --no-cache python3 make g++
COPY package*.json ./
RUN npm ci
COPY tsconfig.json ./
COPY src ./src
RUN npm run build && npm prune --omit=dev

FROM node:22-alpine@sha256:1314fb30ec37592d5845e5a160d522c0e680972aa534549940b8d73bde88481a AS runtime
ARG VERSION=0.2.0
ARG REVISION=unknown
LABEL org.opencontainers.image.title="PiPhi Z-Wave JS sidecar" \
      org.opencontainers.image.source="https://github.com/PiPhi-io/piphi-apps" \
      org.opencontainers.image.version=$VERSION \
      org.opencontainers.image.revision=$REVISION \
      org.opencontainers.image.licenses="Apache-2.0"
WORKDIR /app
ENV NODE_ENV=production \
    PORT=4211 \
    PIPHI_ZWAVE_CACHE_DIR=/var/lib/piphi/zwave-js/cache \
    PIPHI_ZWAVE_LOCK_DIR=/var/lib/piphi/zwave-js/locks
RUN apk add --no-cache libstdc++ \
    && mkdir -p /var/lib/piphi/zwave-js/cache /var/lib/piphi/zwave-js/locks \
    && chown -R node:node /app /var/lib/piphi/zwave-js
COPY --from=build --chown=node:node /app/node_modules ./node_modules
COPY --from=build --chown=node:node /app/dist ./dist
USER node
EXPOSE 4211
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD node -e "fetch('http://127.0.0.1:'+(process.env.PORT||4211)+'/health').then(r=>{if(!r.ok)process.exit(1)}).catch(()=>process.exit(1))"
CMD ["node", "dist/index.js"]
