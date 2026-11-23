FROM python:3.12-slim@sha256:5e2bdb1b0d542d5039cffb8181c65930093949194a65c365dfb1b0fe13a4fa5b AS requirements
WORKDIR /app
RUN pip install --no-cache-dir "pdm==2.29.7"
COPY pyproject.toml pdm.lock ./
RUN pdm export --prod --output /requirements.txt

FROM python:3.12-slim@sha256:5e2bdb1b0d542d5039cffb8181c65930093949194a65c365dfb1b0fe13a4fa5b
ARG RELEASE_VERSION=0.1.15
ARG SOURCE_REVISION=unknown
ARG SOURCE_REPOSITORY=https://github.com/PiPhi-io/piphi-apps
LABEL org.opencontainers.image.source="${SOURCE_REPOSITORY}" \
      org.opencontainers.image.revision="${SOURCE_REVISION}" \
      org.opencontainers.image.version="${RELEASE_VERSION}"
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIPHI_AUTOMATION_LEDGER_PATH=/var/lib/piphi/automation-actions.sqlite3
WORKDIR /app
COPY --from=requirements /requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir --require-hashes -r /tmp/requirements.txt
COPY src ./src
RUN groupadd --system --gid 10001 piphi \
    && useradd --system --uid 10001 --gid piphi --home-dir /app piphi \
    && mkdir -p /var/lib/piphi \
    && chown -R 10001:10001 /var/lib/piphi \
    && chmod -R a-w /app
VOLUME ["/var/lib/piphi"]
USER 10001:10001
EXPOSE 3665
HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:3665/health', timeout=2)"
CMD ["uvicorn", "com_piphi_await_element.app:app", "--app-dir", "/app/src", "--host", "0.0.0.0", "--port", "3665"]
