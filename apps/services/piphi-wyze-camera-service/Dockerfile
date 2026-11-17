FROM python:3.12-slim@sha256:78387bc3881b8273120a12ebe6c1ab22b018ccc2c9adf565ae1ac9b536e184ea AS package

ARG PDM_VERSION=2.29.7
WORKDIR /build
RUN pip install --no-cache-dir "pdm==${PDM_VERSION}"
COPY pyproject.toml pdm.lock ./
RUN pdm export --prod --without-hashes --output requirements.txt

FROM docker.io/mrlt8/wyze-bridge:2.10.3@sha256:af2d638a6d6d52e15ddcfb711e5b905e484b1f519986ad33b9be562b6277b987

ARG RELEASE_VERSION=0.1.5
ARG SOURCE_REVISION=unknown
ARG SOURCE_REPOSITORY=https://github.com/PiPhi-io/piphi-apps
LABEL org.opencontainers.image.title="PiPhi Wyze Camera Bridge" \
      org.opencontainers.image.description="Managed Wyze-to-RTSP bridge for PiPhi camera integrations" \
      org.opencontainers.image.source="${SOURCE_REPOSITORY}" \
      org.opencontainers.image.revision="${SOURCE_REVISION}" \
      org.opencontainers.image.version="${RELEASE_VERSION}" \
      org.opencontainers.image.licenses="AGPL-3.0-only"

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIPHI_ENV=production \
    PIPHI_WYZE_RTSP_PORT=8554

WORKDIR /piphi
COPY --from=package /build/requirements.txt /tmp/piphi-requirements.txt
COPY pyproject.toml ./
COPY src ./src
RUN pip install --no-cache-dir -r /tmp/piphi-requirements.txt \
    && pip install --no-cache-dir --no-deps . \
    && rm /tmp/piphi-requirements.txt \
    && groupadd --system --gid 10001 piphi \
    && useradd --system --uid 10001 --gid piphi --home-dir /nonexistent piphi \
    && chown -R piphi:piphi /tokens /piphi

EXPOSE 8090 8554/tcp
USER piphi
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
  CMD python -c "import os, urllib.request; urllib.request.urlopen('http://127.0.0.1:' + os.getenv('PORT', '8090') + '/health', timeout=3)"
CMD ["python", "-m", "piphi_wyze_camera_service.main"]
