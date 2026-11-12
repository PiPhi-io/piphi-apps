# syntax=docker/dockerfile:1.7

FROM node:24-bookworm-slim AS build
WORKDIR /app
COPY package*.json ./
RUN npm ci
COPY tsconfig.json ./
COPY src ./src
RUN npm run build

FROM node:24-bookworm-slim AS runtime
ENV NODE_ENV=production \
    MATTER_STORAGE_DIR=/var/lib/piphi/matter \
    MATTER_API_HOST=127.0.0.1 \
    MATTER_API_PORT=8710 \
    MATTER_BACKEND_HOST=127.0.0.1 \
    MATTER_BACKEND_PORT=5580 \
    MATTER_MANAGE_BACKEND=true \
    MATTER_ENABLE_BLE=false

RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    libavahi-client3 \
    libdbus-1-3 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY package*.json ./
RUN npm ci --omit=dev && npm cache clean --force
COPY --from=build /app/dist ./dist
COPY src/manifest.json src/behaviors.json src/capability-catalog.json ./src/

RUN mkdir -p /var/lib/piphi/matter && chown -R node:node /var/lib/piphi/matter
USER node

EXPOSE 8710
VOLUME ["/var/lib/piphi/matter"]
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD node -e "fetch('http://127.0.0.1:' + (process.env.PORT || '8710') + '/health').then(r=>{if(!r.ok)process.exit(1)}).catch(()=>process.exit(1))"

CMD ["node", "dist/index.js"]
