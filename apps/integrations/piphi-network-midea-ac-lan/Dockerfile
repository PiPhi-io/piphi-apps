FROM python:3.12-slim
WORKDIR /app
COPY pyproject.toml ./
COPY src ./src
RUN pip install --no-cache-dir .
EXPOSE 4208
CMD ["uvicorn", "piphi_network_midea_ac_lan.main:app", "--host", "0.0.0.0", "--port", "4208"]
