FROM node:22-slim AS widgets
WORKDIR /widgets/print-status
COPY widgets/print-status/package.json widgets/print-status/package-lock.json ./
RUN npm ci --ignore-scripts
COPY widgets/print-status ./
RUN npm run build

FROM python:3.12-slim
WORKDIR /app
COPY pyproject.toml ./
COPY src ./src
RUN pip install --no-cache-dir .
COPY --from=widgets /widgets/print-status/dist ./widgets/print-status/dist
ENV PIPHI_WIDGET_DIR=/app/widgets
EXPOSE 4203
CMD ["uvicorn", "piphi_network_bambu_lab.main:app", "--host", "0.0.0.0", "--port", "4203"]
