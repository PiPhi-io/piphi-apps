FROM node:22-slim AS widgets
WORKDIR /widgets
COPY widgets ./
RUN for widget in sense-energy-flow sense-device-breakdown; do \
      cd "/widgets/$widget" && npm ci --ignore-scripts && npm run build || exit 1; \
    done

FROM python:3.12-slim
WORKDIR /app
RUN groupadd --system --gid 10001 piphi \
    && useradd --system --uid 10001 --gid piphi --home-dir /nonexistent --shell /usr/sbin/nologin piphi \
    && mkdir -p /var/lib/piphi \
    && chown piphi:piphi /var/lib/piphi
COPY pyproject.toml ./
COPY src ./src
RUN pip install --no-cache-dir .
COPY --from=widgets /widgets ./widgets
ENV PIPHI_WIDGET_DIR=/app/widgets
ENV PIPHI_AUTOMATION_LEDGER_PATH=/var/lib/piphi/automation-actions.sqlite3
ENV PYTHONPATH=/app/src
VOLUME ["/var/lib/piphi"]
EXPOSE 8090
USER piphi
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD python -c "import json, urllib.request; json.load(urllib.request.urlopen('http://127.0.0.1:8090/health', timeout=3))" || exit 1
CMD ["uvicorn", "piphi_network_sense.main:app", "--host", "0.0.0.0", "--port", "8090"]
