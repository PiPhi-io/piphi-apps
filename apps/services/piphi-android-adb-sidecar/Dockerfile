FROM python:3.12-slim
WORKDIR /app
COPY pyproject.toml ./
COPY src ./src
RUN pip install --no-cache-dir .
EXPOSE 4213
CMD ["python", "-m", "piphi_android_adb_sidecar.main"]
