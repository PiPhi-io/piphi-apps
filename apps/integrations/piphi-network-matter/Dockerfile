FROM node:22-alpine@sha256:1314fb30ec37592d5845e5a160d522c0e680972aa534549940b8d73bde88481a AS build
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci
COPY tsconfig.json tsconfig.build.json ./
COPY src ./src
RUN npm run build && npm prune --omit=dev

FROM node:22-alpine@sha256:1314fb30ec37592d5845e5a160d522c0e680972aa534549940b8d73bde88481a
WORKDIR /app
ENV NODE_ENV=production PORT=4221 PIPHI_MATTER_CONFIG_PATH=/app/data/config.json
RUN addgroup -S -g 10001 piphi && adduser -S -D -H -u 10001 -G piphi piphi && mkdir -p /app/data && chown -R piphi:piphi /app
COPY --from=build --chown=piphi:piphi /app/package.json /app/package-lock.json ./
COPY --from=build --chown=piphi:piphi /app/node_modules ./node_modules
COPY --from=build --chown=piphi:piphi /app/dist ./dist
USER piphi
EXPOSE 4221
VOLUME ["/app/data"]
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD node -e "fetch('http://127.0.0.1:'+(process.env.PORT||'4221')+'/health').then(r=>process.exit(r.ok?0:1)).catch(()=>process.exit(1))"
CMD ["node", "dist/main.js"]
