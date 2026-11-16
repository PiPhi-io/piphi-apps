FROM python:3.12-slim-trixie@sha256:5e2bdb1b0d542d5039cffb8181c65930093949194a65c365dfb1b0fe13a4fa5b AS requirements
WORKDIR /app
RUN pip install --no-cache-dir "pdm==2.29.7"
COPY pyproject.toml pdm.lock ./
RUN pdm export --prod --output /requirements.txt

FROM python:3.12-slim-trixie@sha256:5e2bdb1b0d542d5039cffb8181c65930093949194a65c365dfb1b0fe13a4fa5b

RUN apt-get update \
    && apt-get install -y --no-install-recommends adb ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY --from=requirements /requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir --require-hashes -r /tmp/requirements.txt
COPY pyproject.toml ./
COPY src ./src
RUN pip install --no-cache-dir --no-deps . \
    && groupadd --gid 10001 piphi \
    && useradd --uid 10001 --gid piphi --home-dir /app/data --no-create-home piphi \
    && mkdir -p /app/data/.android \
    && chown -R piphi:piphi /app/data

ENV HOME=/app/data \
    PIPHI_ADB_HOME=/app/data

USER 10001:10001
EXPOSE 4213
CMD ["python", "-m", "piphi_android_adb_sidecar.main"]
