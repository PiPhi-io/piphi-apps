# syntax=docker/dockerfile:1.7
FROM node:22-bookworm-slim AS build

RUN apt-get update \
    && apt-get install --yes --no-install-recommends git ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY package.json ./
RUN npm install --omit=dev \
    && npm install --no-save \
      typescript@5.9.2 \
      @types/express@5.0.3 \
      @types/express-winston@4.0.2 \
      @types/node@24.5.1 \
      @types/winston@2.4.4

COPY tsconfig.json tsconfig.build.json server.ts ./
COPY lib ./lib
COPY routes ./routes
RUN ./node_modules/.bin/tsc -p tsconfig.build.json \
    && npm prune --omit=dev

FROM node:22-bookworm-slim AS runtime
ENV NODE_ENV=production
WORKDIR /app

COPY --from=build /app/package.json ./package.json
COPY --from=build /app/node_modules ./node_modules
COPY --from=build /app/dist ./dist

EXPOSE 3080
CMD ["node", "dist/server.js"]
