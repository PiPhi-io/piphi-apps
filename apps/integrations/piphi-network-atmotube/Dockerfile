FROM --platform=$BUILDPLATFORM golang:1.25.0-bookworm@sha256:81dc45d05a7444ead8c92a389621fafabc8e40f8fd1a19d7e5df14e61e98bc1a AS build
WORKDIR /src
COPY go.mod go.sum ./
RUN go mod download && go mod verify
COPY . .
ARG TARGETOS=linux
ARG TARGETARCH
RUN test -n "$TARGETARCH" && CGO_ENABLED=0 GOOS="$TARGETOS" GOARCH="$TARGETARCH" \
    go build -mod=readonly -trimpath -ldflags="-s -w -buildid=" -o /out/piphi-network-atmotube . && \
    mkdir -p /out/state-dir

FROM gcr.io/distroless/static-debian12:nonroot@sha256:afa5c872c891853ca7fcf1f12c3edb23f7eeef36189728842dd51042ff57f7ab
ARG RELEASE_VERSION=0.1.7
ARG SOURCE_REVISION=unknown
ARG SOURCE_REPOSITORY=https://github.com/PiPhi-io/piphi-apps
LABEL org.opencontainers.image.title="PiPhi Atmotube integration" \
      org.opencontainers.image.version="$RELEASE_VERSION" \
      org.opencontainers.image.revision="$SOURCE_REVISION" \
      org.opencontainers.image.source="$SOURCE_REPOSITORY" \
      org.opencontainers.image.licenses="NOASSERTION"
COPY --from=build --chown=65532:65532 /out/piphi-network-atmotube /usr/local/bin/piphi-network-atmotube
COPY --from=build --chown=65532:65532 /out/state-dir/ /var/lib/piphi-atmotube/
ENV GIN_MODE=release
USER 65532:65532
VOLUME ["/var/lib/piphi-atmotube"]
EXPOSE 2026
ENTRYPOINT ["/usr/local/bin/piphi-network-atmotube"]
