FROM python:3.12-slim-bookworm AS rtl433-build

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

FROM python:3.12-slim-bookworm AS python-dependencies

WORKDIR /build

COPY pyproject.toml pdm.lock README.md /build/
COPY src /build/src

RUN python -m pip install --no-cache-dir "pdm==2.29.7" \
    && pdm export --prod --without-hashes --output /tmp/requirements.txt \
    && python -m pip wheel --no-cache-dir --wheel-dir /wheels -r /tmp/requirements.txt \
    && python -m pip wheel --no-cache-dir --no-deps --wheel-dir /wheels .

FROM python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    RUNTIME_INGEST_URL=http://127.0.0.1:8090/ingest/rtl433 \
    RADIO_BAND=433mhz \
    RTLSDR_DEVICE=auto \
    RECEIVER_GAIN=auto \
    RTL433_UPSTREAM_REVISION=f15b67699e902522014e7593d060ad37410eda00

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
    && groupadd --system rtl433 \
    && useradd --system --gid rtl433 --groups 46 --home-dir /nonexistent rtl433

USER rtl433

ENTRYPOINT ["tini", "--"]
CMD ["python", "-m", "piphi_rtl433_bridge.service"]
