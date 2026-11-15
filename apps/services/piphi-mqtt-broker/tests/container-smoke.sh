#!/bin/sh
set -eu

image="piphi-mqtt-broker:smoke"
name="piphi-mqtt-smoke-$$"
secrets="${TMPDIR:-/tmp}/piphi-mqtt-smoke-$$"

cleanup() {
  docker rm -f "$name" >/dev/null 2>&1 || true
  rm -rf "$secrets"
}
trap cleanup EXIT HUP INT TERM

mkdir -p "$secrets"
printf '%s' 'smoke-secret' > "$secrets/password"
chmod 0600 "$secrets/password"

docker build -t "$image" .
docker run -d --name "$name" \
  -e MQTT_ALLOW_PLAINTEXT=true \
  -e MQTT_USERNAME=piphi \
  -e MQTT_PASSWORD_SECRET_FILE=/run/secrets/password \
  -v "$secrets:/run/secrets:ro" \
  "$image" >/dev/null

attempt=0
until [ "$(docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{end}}' "$name")" = "healthy" ]; do
  attempt=$((attempt + 1))
  if [ "$attempt" -ge 30 ]; then
    docker logs "$name"
    exit 1
  fi
  sleep 1
done

docker exec "$name" sh -ec '
  mosquitto_sub -V mqttv5 -h 127.0.0.1 -u piphi -P smoke-secret -t piphi/test -C 1 -W 5 > /tmp/message &
  subscriber=$!
  sleep 1
  mosquitto_pub -V mqttv5 -h 127.0.0.1 -u piphi -P smoke-secret -t piphi/test -m ok -q 1
  wait "$subscriber"
  test "$(cat /tmp/message)" = ok
  ! grep -q smoke-secret /mosquitto/config/passwordfile
  test "$(stat -c %a /mosquitto/config/passwordfile)" = 640
'

anonymous="$(docker exec "$name" mosquitto_sub -V mqttv5 -h 127.0.0.1 -t piphi/test -C 1 -W 1 2>&1 || true)"
echo "$anonymous" | grep -q 'Not authorized'

outside="$(docker exec "$name" mosquitto_pub -V mqttv5 -h 127.0.0.1 -u piphi -P smoke-secret -t outside/test -m denied -q 1 2>&1 || true)"
echo "$outside" | grep -q 'Not authorized'

docker exec "$name" mosquitto_pub -V mqttv5 -h 127.0.0.1 -u piphi -P smoke-secret -t piphi/retained -m persisted -q 1 -r
docker restart "$name" >/dev/null
attempt=0
while ! retained="$(docker exec "$name" mosquitto_sub -V mqttv5 -h 127.0.0.1 -u piphi -P smoke-secret -t piphi/retained -C 1 -W 2 2>/dev/null)"; do
  attempt=$((attempt + 1))
  [ "$attempt" -lt 15 ] || exit 1
  sleep 1
done
test "$retained" = persisted

openssl req -x509 -newkey rsa:2048 -nodes -days 1 \
  -subj '/CN=127.0.0.1' -addext 'subjectAltName=IP:127.0.0.1' \
  -keyout "$secrets/server.key" -out "$secrets/server.crt" >/dev/null 2>&1
chmod 0644 "$secrets/server.key" "$secrets/server.crt"
docker rm -f "$name" >/dev/null

docker run -d --name "$name" \
  -e MQTT_USERNAME=piphi \
  -e MQTT_PASSWORD_SECRET_FILE=/run/secrets/password \
  -e MQTT_TLS_ENABLED=true \
  -e MQTT_TLS_CERT_FILE=/run/secrets/server.crt \
  -e MQTT_TLS_KEY_FILE=/run/secrets/server.key \
  -e MQTT_TLS_CA_FILE=/run/secrets/server.crt \
  -v "$secrets:/run/secrets:ro" \
  "$image" >/dev/null

attempt=0
until [ "$(docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{end}}' "$name")" = "healthy" ]; do
  attempt=$((attempt + 1))
  if [ "$attempt" -ge 30 ]; then
    docker logs "$name"
    exit 1
  fi
  sleep 1
done
