#!/bin/sh
set -eu

image="${1:?usage: qualify-release-image.sh IMAGE@sha256:DIGEST VERSION REVISION PLATFORM}"
version="${2:?version is required}"
revision="${3:?revision is required}"
platform="${4:?platform is required}"

echo "$image" | grep -Eq '^.+@sha256:[0-9a-f]{64}$' || {
  echo "qualification requires an immutable sha256 image reference" >&2
  exit 2
}
case "$platform" in
  linux/amd64|linux/arm64) ;;
  *) echo "unsupported qualification platform: $platform" >&2; exit 2 ;;
esac

export PIPHI_MQTT_IMAGE="$image"
export EXPECTED_VERSION="$version"
export EXPECTED_REVISION="$revision"
export DOCKER_DEFAULT_PLATFORM="$platform"
exec sh tests/container-smoke.sh
