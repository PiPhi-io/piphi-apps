FROM docker:27-cli AS docker-cli

FROM python:3.12-slim
WORKDIR /app
COPY pyproject.toml ./
COPY src ./src
COPY --from=docker-cli /usr/local/bin/docker /usr/local/bin/docker
RUN pip install --no-cache-dir .
EXPOSE 8720
CMD ["python", "-m", "piphi_network_zigbee2mqtt.main"]
