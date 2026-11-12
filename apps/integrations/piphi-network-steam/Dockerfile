FROM node:22-alpine AS widget-build
WORKDIR /widget
COPY widgets/steam-activity/package*.json ./
RUN npm ci
COPY widgets/steam-activity ./
RUN npm run build

FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIPHI_WIDGET_DIR=/app/widgets
WORKDIR /app
RUN useradd --create-home --uid 10001 piphi
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --no-cache-dir .
COPY --from=widget-build /widget/dist ./widgets
COPY --from=widget-build /widget/widget.manifest.json ./widgets/widget.manifest.json
USER piphi
EXPOSE 8090
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8090/health', timeout=3)"
CMD ["python", "-m", "piphi_network_steam.main"]
