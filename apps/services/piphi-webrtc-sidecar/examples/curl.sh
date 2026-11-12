#!/usr/bin/env bash
set -euo pipefail

BASE_URL="${BASE_URL:-http://127.0.0.1:8090}"

curl -sS "$BASE_URL/health"
curl -sS "$BASE_URL/diagnostics"
curl -sS "$BASE_URL/ui-config"
curl -sS -X POST "$BASE_URL/config" -H 'content-type: application/json' \
  -d '{"id":"front-door","source_url":"rtsp://user:password@camera.local/live","alias":"Front door"}'
curl -sS "$BASE_URL/entities"
curl -sS "$BASE_URL/v1/cameras/front-door/snapshot" --output snapshot.jpg
