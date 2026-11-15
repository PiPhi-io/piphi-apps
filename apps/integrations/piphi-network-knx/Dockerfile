FROM python:3.12.12-slim@sha256:f3fa41d74a768c2fce8016b98c191ae8c1bacd8f1152870a3f9f87d350920b7c AS builder
WORKDIR /app
COPY pyproject.toml pdm.lock ./
COPY src ./src
RUN pip install --no-cache-dir "pdm==2.29.7" \
    && pdm export --prod --without-hashes -o requirements.txt \
    && pip wheel --no-cache-dir --wheel-dir /wheels -r requirements.txt .

FROM python:3.12.12-slim@sha256:f3fa41d74a768c2fce8016b98c191ae8c1bacd8f1152870a3f9f87d350920b7c
WORKDIR /app
RUN useradd --create-home --uid 10001 piphi
COPY --from=builder /wheels /wheels
RUN pip install --no-cache-dir /wheels/* && rm -rf /wheels
RUN mkdir -p /app/data && chown -R piphi:piphi /app
USER piphi
EXPOSE 4223
HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:4223/health', timeout=2)"
CMD ["uvicorn", "piphi_network_knx.main:app", "--host", "0.0.0.0", "--port", "4223"]
