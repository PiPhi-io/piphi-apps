FROM python:3.12-slim-bookworm@sha256:935c3c5b12357a7e10caa9c1e6ca5692344d97cf229832ef584be2cec9fc03df AS rtl433-build

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        build-essential \
        ca-certificates \
        cmake \
        libtool \
        libusb-1.0-0-dev \
        librtlsdr-dev \
        pkg-config \
    && rm -rf /var/lib/apt/lists/*

ADD --checksum=sha256:bb6ea6d9add6ddeebf960065427a9af0e55829757922b26111fa066b9b0cba31 \
    https://codeload.github.com/merbanan/rtl_433/tar.gz/f15b67699e902522014e7593d060ad37410eda00 \
    /tmp/rtl433.tar.gz

RUN mkdir /tmp/rtl433 \
    && tar -xzf /tmp/rtl433.tar.gz --strip-components=1 -C /tmp/rtl433 \
    && cmake \
        -S /tmp/rtl433 \
        -B /tmp/rtl433/build \
        -DCMAKE_BUILD_TYPE=Release \
        -DENABLE_RTLSDR=ON \
        -DENABLE_SOAPYSDR=OFF \
        -DENABLE_OPENSSL=OFF \
        -DBUILD_DOCUMENTATION=OFF \
    && cmake --build /tmp/rtl433/build --parallel 2 \
    && cmake --install /tmp/rtl433/build

FROM python:3.12-slim-bookworm@sha256:935c3c5b12357a7e10caa9c1e6ca5692344d97cf229832ef584be2cec9fc03df AS python-dependencies

WORKDIR /build

COPY pyproject.toml pdm.lock README.md /build/
COPY src /build/src

RUN python -m pip install --no-cache-dir "pdm==2.29.7" \
    && pdm export --prod --output /tmp/requirements.txt \
    && python -m pip wheel --no-cache-dir --require-hashes --wheel-dir /wheels -r /tmp/requirements.txt \
    && python -m pip wheel --no-cache-dir --no-deps --wheel-dir /wheels .

FROM python:3.12-slim-bookworm@sha256:935c3c5b12357a7e10caa9c1e6ca5692344d97cf229832ef584be2cec9fc03df
ARG RELEASE_VERSION=0.2.1
ARG SOURCE_REVISION=unknown
ARG SOURCE_REPOSITORY=https://github.com/PiPhi-io/piphi-apps
LABEL org.opencontainers.image.source="${SOURCE_REPOSITORY}" \
      org.opencontainers.image.revision="${SOURCE_REVISION}" \
      org.opencontainers.image.version="${RELEASE_VERSION}"

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    RUNTIME_INGEST_URL=http://127.0.0.1:8090/ingest/rtl433 \
    RADIO_BAND=433mhz \
    RTLSDR_DEVICE=auto \
    RECEIVER_GAIN=auto \
    RTL433_UPSTREAM_REVISION=f15b67699e902522014e7593d060ad37410eda00 \
    PIPHI_RTL433_STATE_PATH=/var/lib/piphi/radio-config.json

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        ca-certificates \
        libusb-1.0-0 \
        librtlsdr0 \
        tini \
    && rm -rf /var/lib/apt/lists/*

COPY --from=rtl433-build /usr/local/bin/rtl_433 /usr/local/bin/rtl_433

COPY --from=python-dependencies /wheels /wheels
RUN pip install --no-cache-dir --no-index /wheels/* \
    && rm -rf /wheels

RUN getent group 46 >/dev/null || groupadd --gid 46 plugdev \
    && groupadd --system --gid 10001 rtl433 \
    && useradd --system --uid 10001 --gid 10001 --groups 46 --home-dir /app rtl433 \
    && mkdir -p /var/lib/piphi \
    && chown -R 10001:10001 /app /var/lib/piphi

VOLUME ["/var/lib/piphi"]
EXPOSE 8091
USER rtl433
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD python -c "import json, urllib.request; data=json.load(urllib.request.urlopen('http://127.0.0.1:8091/health', timeout=3)); assert data['status'] == 'ok'"

ENTRYPOINT ["tini", "--"]
CMD ["python", "-m", "piphi_rtl433_bridge.service"]
