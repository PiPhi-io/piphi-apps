FROM python:3.12-slim
WORKDIR /app
COPY pyproject.toml ./
COPY src ./src
RUN pip install --no-cache-dir .
RUN addgroup --system piphi && adduser --system --ingroup piphi piphi \
    && mkdir -p /var/lib/piphi \
    && chown -R piphi:piphi /var/lib/piphi
ENV PIPHI_AUTOMATION_LEDGER_PATH=/var/lib/piphi/automation-actions.sqlite3
VOLUME ["/var/lib/piphi"]
EXPOSE 8090
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8090/health', timeout=3)"
USER piphi
CMD ["uvicorn", "solar_edge.main:app", "--host", "0.0.0.0", "--port", "8090"]
