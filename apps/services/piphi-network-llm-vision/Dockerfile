FROM python:3.12-slim
WORKDIR /app
COPY pyproject.toml ./
COPY src ./src
RUN pip install --no-cache-dir .
EXPOSE 4209
CMD ["python", "-m", "piphi_network_llm_vision.main"]
