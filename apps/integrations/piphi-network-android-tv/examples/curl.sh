#!/usr/bin/env bash
set -euo pipefail

BASE_URL="${BASE_URL:-http://127.0.0.1:4220}"
CONFIG_ID="${CONFIG_ID:-living-room}"
TV_HOST="${TV_HOST:-192.168.1.50}"

curl -sS "$BASE_URL/health"
curl -sS "$BASE_URL/diagnostics"
curl -sS "$BASE_URL/ui-config"
curl -sS -X POST "$BASE_URL/discover" -H 'content-type: application/json' -d '{}'
if [[ -z "${PAIRING_SESSION_ID:-}" || -z "${PAIRING_PIN:-}" ]]; then
  curl -sS -X POST "$BASE_URL/pairing/start" -H 'content-type: application/json' -d "{\"config_id\":\"$CONFIG_ID\",\"host\":\"$TV_HOST\"}"
  echo "Set PAIRING_SESSION_ID and PAIRING_PIN from the response and television, then run again."
  exit 0
fi
curl -sS -X POST "$BASE_URL/pairing/$PAIRING_SESSION_ID/finish" -H 'content-type: application/json' -d "{\"pin\":\"$PAIRING_PIN\"}"
curl -sS -X POST "$BASE_URL/config" -H 'content-type: application/json' -d "{\"id\":\"$CONFIG_ID\",\"host\":\"$TV_HOST\",\"alias\":\"Living Room\"}"
curl -sS "$BASE_URL/entities"
curl -sS -X POST "$BASE_URL/command" -H 'content-type: application/json' -d "{\"contract_version\":\"automation.runtime.command.v1\",\"command\":\"send_key\",\"target\":{\"config_id\":\"$CONFIG_ID\"},\"params\":{\"key\":\"HOME\"},\"capability\":\"device.send_key\",\"capability_requirements\":[\"device.send_key\"]}"
