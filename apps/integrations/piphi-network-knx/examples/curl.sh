#!/usr/bin/env bash
set -euo pipefail

BASE_URL="${BASE_URL:-http://127.0.0.1:4223}"
TOKEN="${PIPHI_INTEGRATION_INTERNAL_TOKEN:?set PIPHI_INTEGRATION_INTERNAL_TOKEN}"
AUTH=(-H "X-PiPhi-Integration-Token: $TOKEN")

curl -fsS "$BASE_URL/health"
curl -fsS "${AUTH[@]}" "$BASE_URL/diagnostics"
curl -fsS "${AUTH[@]}" "$BASE_URL/ui-config"
curl -fsS "${AUTH[@]}" -X POST "$BASE_URL/discover" -H 'content-type: application/json' --data @examples/discovery-request.json
curl -fsS "${AUTH[@]}" -X POST "$BASE_URL/config" -H 'content-type: application/json' --data @examples/config.json
curl -fsS "${AUTH[@]}" "$BASE_URL/entities"
curl -fsS "${AUTH[@]}" -X POST "$BASE_URL/command" -H 'content-type: application/json' --data @examples/command.json
