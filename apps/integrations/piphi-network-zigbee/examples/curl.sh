#!/usr/bin/env bash
set -euo pipefail

BASE_URL="${BASE_URL:-http://127.0.0.1:8730}"

curl -sS "$BASE_URL/health"
curl -sS "$BASE_URL/diagnostics"
curl -sS "$BASE_URL/ui-config"
curl -sS -X POST "$BASE_URL/discover" -H 'content-type: application/json' -d '{"inputs":{"device":{"friendly_name":"smoke_light","ieee_address":"0x00158d0000smoke01","definition":{"model":"SMOKE-TEST","vendor":"PiPhi","exposes":[{"type":"light","features":[{"property":"state","access":7},{"property":"brightness","access":7}]}]}}}}'
curl -sS -X POST "$BASE_URL/config" -H 'content-type: application/json' -d '{"id":"demo-device","friendly_name":"smoke_light","alias":"Smoke Light","ieee_address":"0x00158d0000smoke01","mqtt_server":"mqtt://127.0.0.1:1883","mqtt_base_topic":"zigbee2mqtt","capabilities":["state","brightness_percent"],"exposes":[{"property":"state","access":{"published":true,"set":true,"get":true}},{"property":"brightness","access":{"published":true,"set":true,"get":true}}]}'
curl -sS "$BASE_URL/entities"
curl -sS "$BASE_URL/state"
curl -sS -X POST "$BASE_URL/command" -H 'content-type: application/json' -d '{"contract_version":"automation.runtime.command.v1","command":"set_state","target":{"config_id":"demo-device","device_id":"demo-device"},"params":{"on":true},"capability":"action.set_state","capability_requirements":["action.set_state"],"dry_run":true}'
curl -sS -X POST "$BASE_URL/command" -H 'content-type: application/json' -d '{"contract_version":"automation.runtime.command.v1","command":"refresh","target":{"config_id":"demo-device","device_id":"demo-device"},"params":{},"capability":"device.refresh","capability_requirements":["device.refresh"],"dry_run":true}'
