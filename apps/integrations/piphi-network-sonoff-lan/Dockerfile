FROM python:3.12-slim@sha256:5e2bdb1b0d542d5039cffb8181c65930093949194a65c365dfb1b0fe13a4fa5b AS requirements
WORKDIR /app
RUN pip install --no-cache-dir "pdm==2.29.7"
COPY pyproject.toml pdm.lock ./
RUN pdm export --prod --output /requirements.txt

FROM python:3.12-slim@sha256:5e2bdb1b0d542d5039cffb8181c65930093949194a65c365dfb1b0fe13a4fa5b
ARG RELEASE_VERSION=0.2.0
ARG SOURCE_REVISION=unknown
ARG SOURCE_REPOSITORY=https://github.com/PiPhi-io/piphi-apps
LABEL org.opencontainers.image.source="${SOURCE_REPOSITORY}" \
      org.opencontainers.image.revision="${SOURCE_REVISION}" \
      org.opencontainers.image.version="${RELEASE_VERSION}"
WORKDIR /app
COPY --from=requirements /requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir --require-hashes -r /tmp/requirements.txt
COPY pyproject.toml ./
COPY src ./src
RUN pip install --no-cache-dir --no-deps . \
    && groupadd --system --gid 10001 piphi \
    && useradd --system --uid 10001 --gid piphi --home-dir /app piphi \
    && mkdir -p /app/data \
    && chown -R piphi:piphi /app
USER 10001:10001
EXPOSE 4202
HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:4202/health', timeout=2)"
CMD ["uvicorn", "piphi_network_sonoff_lan.main:app", "--host", "0.0.0.0", "--port", "4202"]
