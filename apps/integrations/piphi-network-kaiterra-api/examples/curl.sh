#!/usr/bin/env bash
set -euo pipefail

BASE_URL="${BASE_URL:-http://127.0.0.1:8090}"
: "${PIPHI_CONTAINER_ID:?set PIPHI_CONTAINER_ID}"
: "${PIPHI_INTEGRATION_TOKEN:?set PIPHI_INTEGRATION_TOKEN}"

auth=(
  -H "X-Container-Id: ${PIPHI_CONTAINER_ID}"
  -H "X-PiPhi-Integration-Token: ${PIPHI_INTEGRATION_TOKEN}"
)

curl -sS "$BASE_URL/health"
curl -sS "${auth[@]}" "$BASE_URL/contract"
curl -sS "${auth[@]}" "$BASE_URL/ui-config"

# Configuration is intentionally not scripted here: Core supplies the secret API
# key and UDID over the authenticated runtime contract.
