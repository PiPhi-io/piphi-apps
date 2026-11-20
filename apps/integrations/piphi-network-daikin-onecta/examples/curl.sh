#!/usr/bin/env bash
set -euo pipefail

BASE_URL="${BASE_URL:-http://127.0.0.1:4215}"
RUNTIME_TOKEN="${PIPHI_INTEGRATION_INTERNAL_TOKEN:?Core runtime token is required}"
OAUTH_SUBJECT="${ONECTA_OAUTH_SUBJECT:?Core-managed OAuth subject is required}"
ACCESS_TOKEN="${ONECTA_ACCESS_TOKEN:?Core-managed access token is required}"
AUTH_HEADER="X-PiPhi-Integration-Token: ${RUNTIME_TOKEN}"

curl -sS "$BASE_URL/health"
curl -sS -H "$AUTH_HEADER" "$BASE_URL/ui-config"
curl -sS -X POST "$BASE_URL/config" -H "$AUTH_HEADER" -H 'content-type: application/json' \
  -d "{\"id\":\"onecta-account\",\"oauth_subject\":\"${OAUTH_SUBJECT}\",\"access_token\":\"${ACCESS_TOKEN}\",\"poll_interval_seconds\":900,\"enable_climate_control\":false}"
curl -sS -H "$AUTH_HEADER" "$BASE_URL/entities"
curl -sS -X POST "$BASE_URL/command" -H "$AUTH_HEADER" -H 'content-type: application/json' \
  -d '{"command":"refresh","target":{"config_id":"onecta-account"},"params":{}}'
