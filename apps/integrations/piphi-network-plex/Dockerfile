FROM python:3.12-slim

RUN groupadd --system --gid 10001 piphi \
    && useradd --system --uid 10001 --gid piphi --home-dir /nonexistent --shell /usr/sbin/nologin piphi \
    && mkdir -p /var/lib/piphi \
    && chown piphi:piphi /var/lib/piphi

WORKDIR /app
COPY pyproject.toml ./
COPY src ./src
COPY widgets ./widgets
ENV PIPHI_WIDGETS_PATH=/app/widgets
ENV PIPHI_AUTOMATION_LEDGER_PATH=/var/lib/piphi/automation-actions.sqlite3
RUN pip install --no-cache-dir .
VOLUME ["/var/lib/piphi"]
EXPOSE 8091
USER piphi
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD python -c "import json, urllib.request; json.load(urllib.request.urlopen('http://127.0.0.1:8091/health', timeout=3))" || exit 1
CMD ["uvicorn", "piphi_network_plex.main:app", "--host", "0.0.0.0", "--port", "8091"]
