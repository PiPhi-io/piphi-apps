#!/usr/bin/env bash
set -euo pipefail

BASE_URL="${BASE_URL:-http://127.0.0.1:4204}"

curl -sS "$BASE_URL/health"
curl -sS "$BASE_URL/diagnostics"
curl -sS "$BASE_URL/ui-config"
curl -sS -X POST "$BASE_URL/discover" -H 'content-type: application/json' -d '{"inputs":{"host":"AA:BB:CC:DD:EE:FF"}}'
curl -sS -X POST "$BASE_URL/config" -H 'content-type: application/json' -d '{"id":"living-room-bthome","host":"AA:BB:CC:DD:EE:FF","alias":"Living room sensor"}'
curl -sS "$BASE_URL/entities"
curl -sS -X POST "$BASE_URL/command" -H 'content-type: application/json' -d '{"contract_version":"automation.runtime.command.v1","command":"refresh","target":{"config_id":"living-room-bthome","device_id":"living-room-bthome"},"params":{},"capability":"device.refresh","capability_requirements":["device.refresh"]}'
