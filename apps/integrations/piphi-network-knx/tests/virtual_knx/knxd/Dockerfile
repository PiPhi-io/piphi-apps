# knxd 0.14.73-1 (GPL-2.0-only) from Debian trixie.
# The base digest and package version match knx-interop v0.9.2.
FROM debian:trixie-slim@sha256:a72b4433de1cf7d6bae0c4cee74d0547f58601a643b3375f070c51600d63b6b2

RUN apt-get update -qq \
    && apt-get install -y -qq --no-install-recommends knxd=0.14.73-1 \
    && rm -rf /var/lib/apt/lists/*

COPY knxd.ini /etc/knxd.ini

EXPOSE 3671/tcp 3671/udp

ENTRYPOINT ["knxd", "/etc/knxd.ini"]
