FROM python:3.12-slim

WORKDIR /app
COPY pyproject.toml ./
COPY src ./src
RUN pip install --no-cache-dir .
RUN mkdir -p /.piphinetwork && chown -R 65532:65532 /.piphinetwork

EXPOSE 3090
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:3090/health', timeout=3)"
USER 65532:65532
CMD ["uvicorn", "piphi_network_tesla_ev.main:app", "--host", "0.0.0.0", "--port", "3090"]
