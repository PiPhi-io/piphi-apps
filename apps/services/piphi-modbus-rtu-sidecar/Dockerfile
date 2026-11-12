FROM python:3.12-slim
WORKDIR /app
COPY pyproject.toml ./
COPY src ./src
RUN pip install --no-cache-dir .
EXPOSE 4212
CMD ["python", "-m", "piphi_modbus_rtu_sidecar.main"]
