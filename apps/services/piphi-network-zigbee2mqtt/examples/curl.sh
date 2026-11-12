#!/usr/bin/env bash
set -euo pipefail

BASE_URL="${BASE_URL:-http://127.0.0.1:8720}"

curl -sS "$BASE_URL/health"
curl -sS "$BASE_URL/diagnostics"
curl -sS "$BASE_URL/v1/snapshot"
curl -sS "$BASE_URL/v1/adapters"
curl -sS "$BASE_URL/ui-config"
curl -sS -X POST "$BASE_URL/discover" -H 'content-type: application/json' -d '{"inputs":{"serial_port":"/dev/ttyZigbee"}}'
curl -sS -X POST "$BASE_URL/config" -H 'content-type: application/json' -d '{"id":"zigbee2mqtt-bridge","host":"127.0.0.1","alias":"Zigbee2MQTT Bridge","serial_port":"/dev/ttyZigbee","adapter":"ember","mqtt_server":"mqtt://127.0.0.1:1883","mqtt_base_topic":"zigbee2mqtt","data_path":"/app/data"}'
curl -sS -X POST "$BASE_URL/v1/config/render" -H 'content-type: application/json' -d '{"config":{"mqtt":{"server":"mqtt://127.0.0.1:1883","base_topic":"zigbee2mqtt"},"serial":{"port":"/dev/ttyZigbee","adapter":"ember"},"runtime":"docker","data_path":"/app/data"}}'
curl -sS -X POST "$BASE_URL/v1/supervisor/start" -H 'content-type: application/json' -d '{"mode":"docker","dry_run":true,"docker":{"host_data_path":"/var/lib/piphi/zigbee2mqtt","device_path":"/dev/ttyZigbee"}}'
curl -sS -X POST "$BASE_URL/v1/supervisor/logs" -H 'content-type: application/json' -d '{"mode":"docker","dry_run":true,"tail":50,"docker":{"host_data_path":"/var/lib/piphi/zigbee2mqtt"}}'
curl -sS -X POST "$BASE_URL/v1/prerequisites" -H 'content-type: application/json' -d '{"mode":"docker","dry_run":true,"docker":{"host_data_path":"/var/lib/piphi/zigbee2mqtt","device_path":"/dev/ttyZigbee"}}'
curl -sS -X POST "$BASE_URL/v1/apply" -H 'content-type: application/json' -d '{"config_path":"/tmp/piphi-zigbee2mqtt-example.yaml","restart_policy":"never","config":{"mqtt":{"server":"mqtt://127.0.0.1:1883","base_topic":"zigbee2mqtt"},"serial":{"port":"/dev/ttyZigbee","adapter":"ember"},"runtime":"docker","data_path":"/app/data"},"mqtt_check":{"server":"mqtt://127.0.0.1:1883","dry_run":true}}'
curl -sS -X POST "$BASE_URL/v1/mqtt/check" -H 'content-type: application/json' -d '{"server":"mqtt://127.0.0.1:1883","dry_run":true}'
curl -sS -X POST "$BASE_URL/v1/devices" -H 'content-type: application/json' -d '{"server":"mqtt://127.0.0.1:1883","base_topic":"zigbee2mqtt","dry_run":true}'
curl -sS -X POST "$BASE_URL/v1/permit-join" -H 'content-type: application/json' -d '{"server":"mqtt://127.0.0.1:1883","base_topic":"zigbee2mqtt","time":60,"dry_run":true}'
curl -sS "$BASE_URL/entities"
curl -sS -X POST "$BASE_URL/command" -H 'content-type: application/json' -d '{"contract_version":"automation.runtime.command.v1","command":"refresh","target":{"config_id":"zigbee2mqtt-bridge","device_id":"zigbee2mqtt-bridge"},"params":{},"capability":"device.refresh","capability_requirements":["device.refresh"]}'
