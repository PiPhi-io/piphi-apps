# syntax=docker/dockerfile:1.7

FROM node:24-bookworm-slim@sha256:873f586f3794f52281bd039bf02c048a0be08fde619338f9941bad1eb6b34530 AS build
WORKDIR /app
COPY package*.json ./
RUN npm ci --ignore-scripts
COPY tsconfig.json ./
COPY src ./src
RUN npm run build

FROM node:24-bookworm-slim@sha256:873f586f3794f52281bd039bf02c048a0be08fde619338f9941bad1eb6b34530 AS runtime
ENV NODE_ENV=production \
    MATTER_STORAGE_DIR=/var/lib/piphi/matter \
    MATTER_API_HOST=127.0.0.1 \
    MATTER_API_PORT=8710 \
    MATTER_BACKEND_HOST=127.0.0.1 \
    MATTER_BACKEND_PORT=5580 \
    MATTER_MANAGE_BACKEND=true \
    MATTER_ENABLE_BLE=false \
    NOBLE_BINDINGS=dbus

RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    libavahi-client3 \
    libdbus-1-3 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY package*.json ./
RUN npm ci --omit=dev --ignore-scripts && npm cache clean --force
COPY --from=build /app/dist ./dist
COPY src/manifest.json src/behaviors.json src/capability-catalog.json ./src/

RUN groupmod --gid 10001 node && usermod --uid 10001 --gid 10001 node \
    && mkdir -p /var/lib/piphi/matter \
    && chown -R node:node /var/lib/piphi/matter /app
USER node

EXPOSE 8710
VOLUME ["/var/lib/piphi/matter"]
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD node -e "fetch('http://127.0.0.1:' + (process.env.PORT || '8710') + '/health').then(r=>{if(!r.ok)process.exit(1)}).catch(()=>process.exit(1))"

CMD ["node", "dist/index.js"]
