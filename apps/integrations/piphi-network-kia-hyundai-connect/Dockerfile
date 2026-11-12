FROM python:3.12-slim
WORKDIR /app
COPY pyproject.toml ./
COPY src ./src
RUN pip install --no-cache-dir .
EXPOSE 4217
CMD ["uvicorn", "piphi_network_kia_hyundai_connect.main:app", "--host", "0.0.0.0", "--port", "4217"]
