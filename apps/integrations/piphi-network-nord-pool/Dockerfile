FROM node:22-slim AS widgets
WORKDIR /widgets/nord-pool-price
COPY widgets/nord-pool-price/package.json widgets/nord-pool-price/package-lock.json ./
RUN npm ci --ignore-scripts
COPY widgets/nord-pool-price ./
RUN npm run build

FROM python:3.12-slim
WORKDIR /app
COPY pyproject.toml ./
COPY src ./src
RUN pip install --no-cache-dir .
COPY --from=widgets /widgets ./widgets
ENV PIPHI_WIDGET_DIR=/app/widgets
EXPOSE 4214
CMD ["uvicorn", "piphi_network_nord_pool.main:app", "--host", "0.0.0.0", "--port", "4214"]
