#!/usr/bin/env bash
set -euo pipefail

ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
IMAGE=piphi-knxd-virtual:0.14.73-1
CONTAINER=piphi-knxd-virtual
PORT=3671

cleanup() {
  docker rm -f "$CONTAINER" >/dev/null 2>&1 || true
}
trap cleanup EXIT

docker build -t "$IMAGE" "$ROOT/tests/virtual_knx/knxd"
cleanup
docker run --detach --rm \
  --name "$CONTAINER" \
  --network host \
  "$IMAGE" >/dev/null

for _ in $(seq 1 50); do
  if docker logs "$CONTAINER" 2>&1 | grep -q "Layer 0"; then
    break
  fi
  if ! docker inspect "$CONTAINER" >/dev/null 2>&1; then
    docker logs "$CONTAINER" >&2 || true
    exit 1
  fi
  sleep 0.1
done

cd "$ROOT"
PIPHI_KNX_VIRTUAL_TEST=1 \
PIPHI_KNX_VIRTUAL_HOST=127.0.0.1 \
PIPHI_KNX_VIRTUAL_PORT="$PORT" \
PDM_IGNORE_ACTIVE_VENV=1 pdm run pytest --no-cov -q tests/test_virtual_knx.py
