FROM python:3.12-slim
WORKDIR /app
COPY pyproject.toml ./
COPY src ./src
RUN pip install --no-cache-dir .
RUN addgroup --system --gid 10001 piphi \
    && adduser --system --uid 10001 --ingroup piphi --home /app piphi \
    && mkdir -p /app/data \
    && chown -R piphi:piphi /app
USER 10001:10001
EXPOSE 4222
CMD ["uvicorn", "piphi_network_modbus.main:app", "--host", "0.0.0.0", "--port", "4222"]
