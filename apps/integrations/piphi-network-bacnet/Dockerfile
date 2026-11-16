FROM python:3.12-slim
WORKDIR /app
COPY pyproject.toml ./
COPY src ./src
RUN pip install --no-cache-dir .
RUN groupadd --system piphi \
    && useradd --system --gid piphi --home-dir /app piphi \
    && mkdir -p /app/data \
    && chown -R piphi:piphi /app
ENV PIPHI_AUTOMATION_LEDGER_PATH=/app/data/automation-actions.sqlite3
USER piphi
EXPOSE 4224
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:4224/health', timeout=3).read()"]
CMD ["uvicorn", "piphi_network_bacnet.main:app", "--host", "0.0.0.0", "--port", "4224"]
