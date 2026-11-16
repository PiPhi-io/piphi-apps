#!/usr/bin/env bash
set -euo pipefail

BASE_URL="${BASE_URL:-http://127.0.0.1:4212}"

curl -sS "$BASE_URL/health"
curl -sS "$BASE_URL/diagnostics"
curl -sS "$BASE_URL/ui-config"
curl -sS -X POST "$BASE_URL/discover" -H 'content-type: application/json' -d '{"inputs":{}}'
curl -sS -X POST "$BASE_URL/config" -H 'content-type: application/json' -d '{"id":"demo-device","alias":"Agile tariff","product_code":"AGILE-FLEX-22-11-25","tariff_code":"E-1R-AGILE-FLEX-22-11-25-A"}'
curl -sS "$BASE_URL/entities"
curl -sS -X POST "$BASE_URL/command" -H 'content-type: application/json' -d '{"contract_version":"automation.runtime.command.v1","command":"refresh","target":{"config_id":"demo-device","device_id":"demo-device"},"params":{},"capability":"device.refresh","capability_requirements":["device.refresh"]}'
