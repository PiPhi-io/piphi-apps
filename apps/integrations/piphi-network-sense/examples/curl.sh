#!/usr/bin/env bash
set -euo pipefail

BASE_URL="${BASE_URL:-http://127.0.0.1:8090}"

curl -sS "$BASE_URL/health"
curl -sS "$BASE_URL/diagnostics"
curl -sS "$BASE_URL/ui-config"
curl -sS -X POST "$BASE_URL/discover" -H 'content-type: application/json' -d '{"inputs":{"host":"127.0.0.1"}}'
curl -sS -X POST "$BASE_URL/config" -H 'content-type: application/json' -d '{"id":"sense-account","email":"owner@example.com","password":"change-me","alias":"Sense Home"}'
curl -sS "$BASE_URL/entities"
curl -sS -X POST "$BASE_URL/command" -H 'content-type: application/json' -d '{"contract_version":"automation.runtime.command.v1","command":"refresh","target":{"config_id":"sense-account","device_id":"sense-account"},"params":{},"capability":"device.refresh","capability_requirements":["device.refresh"]}'
