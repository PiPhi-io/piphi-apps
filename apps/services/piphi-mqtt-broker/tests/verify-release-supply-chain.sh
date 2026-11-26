#!/bin/sh
set -eu

image="${1:?usage: verify-release-supply-chain.sh IMAGE@sha256:DIGEST}"
echo "$image" | grep -Eq '^ghcr\.io/piphi-io/mqtt-broker@sha256:[0-9a-f]{64}$' || {
  echo "verification requires the immutable PiPhi MQTT image digest" >&2
  exit 2
}
command -v jq >/dev/null
command -v gh >/dev/null
command -v trivy >/dev/null

index="$(docker buildx imagetools inspect --raw "$image")"
runtime_platforms="$(echo "$index" | jq -r '.manifests[] | select(.platform.architecture != "unknown") | "\(.platform.os)/\(.platform.architecture)"' | sort -u)"
echo "$runtime_platforms" | grep -qx 'linux/amd64'
echo "$runtime_platforms" | grep -qx 'linux/arm64'
test "$(echo "$runtime_platforms" | wc -l)" -eq 2

# BuildKit emits an attestation manifest for each runtime platform. Those
# manifests carry the max-mode provenance and SPDX SBOM requested by release CI.
test "$(echo "$index" | jq '[.manifests[] | select(.platform.os == "unknown" and .platform.architecture == "unknown" and .annotations["vnd.docker.reference.type"] == "attestation-manifest")] | length')" -eq 2

# The repository release job adds GitHub's signed build-provenance attestation
# after the image index is published.
gh attestation verify "oci://$image" --repo PiPhi-io/piphi-apps >/dev/null

for platform in linux/amd64 linux/arm64; do
  trivy image --quiet --scanners vuln --severity HIGH,CRITICAL --ignore-unfixed --exit-code 1 --platform "$platform" "$image"
done
