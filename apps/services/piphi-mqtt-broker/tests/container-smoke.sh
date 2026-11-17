#!/bin/sh
set -eu

image="piphi-mqtt-broker:smoke"
name="piphi-mqtt-smoke-$$"
secrets="${TMPDIR:-/tmp}/piphi-mqtt-smoke-$$"

cleanup() {
  docker rm -f "$name" >/dev/null 2>&1 || true
  if [ -d "$secrets/restored-data" ]; then
    docker run --rm --entrypoint sh -v "$secrets:/cleanup" "$image" -c 'chmod -R 0777 /cleanup/restored-data' >/dev/null 2>&1 || true
  fi
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
docker exec "$name" node /app/dist/src/healthcheck.js --liveness

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

docker exec "$name" sh -ec 'head -c 1048577 /dev/zero | mosquitto_pub -V mqttv5 -h 127.0.0.1 -u piphi -P smoke-secret -t piphi/oversized -s -q 1 -r' >/dev/null 2>&1 || true
if docker exec "$name" mosquitto_sub -V mqttv5 -h 127.0.0.1 -u piphi -P smoke-secret -t piphi/oversized -C 1 -W 2 >/dev/null 2>&1; then
  echo "Oversized packet was accepted" >&2
  exit 1
fi

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

# Qualify distinct principals, cross-workload denial, credential rotation with
# forced disconnect, and restore into a fresh broker container.
docker rm -f "$name" >/dev/null
printf '%s' 'alpha-one' > "$secrets/alpha-password"
printf '%s' 'beta-secret' > "$secrets/beta-password"
printf '%s' 'health-secret' > "$secrets/health-password"
cat > "$secrets/policy.json" <<'JSON'
{
  "schema_version": 1,
  "principals": [
    {"username":"alpha","namespace":"alpha","password_secret_file":"/run/secrets/alpha-password","read":["piphi/alpha/#"],"write":["piphi/alpha/#"],"health":false},
    {"username":"beta","namespace":"beta","password_secret_file":"/run/secrets/beta-password","read":["piphi/beta/#"],"write":["piphi/beta/#"],"health":false},
    {"username":"health","namespace":"_health","password_secret_file":"/run/secrets/health-password","read":["piphi/_health/#"],"write":["piphi/_health/#"],"health":true}
  ]
}
JSON
chmod 0600 "$secrets"/*-password "$secrets/policy.json"
mkdir -p "$secrets/restored-data"
docker run -d --name "$name" --restart unless-stopped \
  -e MQTT_ALLOW_PLAINTEXT=true \
  -e MQTT_AUTH_POLICY_FILE=/run/secrets/policy.json \
  -v "$secrets:/run/secrets:ro" \
  "$image" >/dev/null
attempt=0
until [ "$(docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{end}}' "$name")" = "healthy" ]; do
  attempt=$((attempt + 1)); [ "$attempt" -lt 30 ] || { docker logs "$name"; exit 1; }; sleep 1
done
docker exec "$name" mosquitto_pub -V mqttv5 -h 127.0.0.1 -u alpha -P alpha-one -t piphi/alpha/retained -m alpha-state -q 1 -r
cross_tenant="$(docker exec "$name" mosquitto_sub -V mqttv5 -h 127.0.0.1 -u beta -P beta-secret -t piphi/alpha/# -C 1 -W 2 2>&1 || true)"
# A retained alpha message exists; timing out proves beta cannot receive it.
echo "$cross_tenant" | grep -q 'Timed out'
reserved_sys="$(docker exec "$name" mosquitto_pub -V mqttv5 -h 127.0.0.1 -u alpha -P alpha-one -t '$SYS/piphi-test' -m denied -q 1 2>&1 || true)"
echo "$reserved_sys" | grep -q 'Not authorized'
reserved_control="$(docker exec "$name" mosquitto_pub -V mqttv5 -h 127.0.0.1 -u alpha -P alpha-one -t '$CONTROL/piphi-test' -m denied -q 1 2>&1 || true)"
echo "$reserved_control" | grep -q 'Not authorized'

printf '%s' 'alpha-two' > "$secrets/alpha-password"
before_restart="$(docker inspect -f '{{.RestartCount}}' "$name")"
docker exec "$name" /app/docker/credentials-admin.sh --disconnect-existing >/dev/null 2>&1 || true
attempt=0
until [ "$(docker inspect -f '{{.RestartCount}}' "$name")" -gt "$before_restart" ]; do
  attempt=$((attempt + 1)); [ "$attempt" -lt 20 ] || { docker logs "$name"; exit 1; }; sleep 1
done
attempt=0
until [ "$(docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{end}}' "$name")" = "healthy" ]; do
  attempt=$((attempt + 1)); [ "$attempt" -lt 40 ] || { docker logs "$name"; exit 1; }; sleep 1
done
old_password="$(docker exec "$name" mosquitto_sub -V mqttv5 -h 127.0.0.1 -u alpha -P alpha-one -t piphi/alpha/# -C 1 -W 1 2>&1 || true)"
echo "$old_password" | grep -q 'Not authorized'
docker exec "$name" mosquitto_pub -V mqttv5 -h 127.0.0.1 -u alpha -P alpha-two -t piphi/alpha/current -m rotated -q 1
docker exec "$name" grep -q 'reload-and-disconnect' /mosquitto/log/security-audit.jsonl

cp "$secrets/policy.json" "$secrets/policy.valid"
printf '%s' '{invalid' > "$secrets/policy.json"
if docker exec "$name" /app/docker/credentials-admin.sh >/dev/null 2>&1; then
  echo "Malformed credential policy was accepted" >&2
  exit 1
fi
mv "$secrets/policy.valid" "$secrets/policy.json"
docker exec "$name" mosquitto_pub -V mqttv5 -h 127.0.0.1 -u alpha -P alpha-two -t piphi/alpha/recovery -m recovered -q 1
docker exec "$name" /app/docker/credentials-admin.sh >/dev/null
docker exec "$name" grep -q '"action":"reload"' /mosquitto/log/security-audit.jsonl

docker stop "$name" >/dev/null
docker cp "$name:/mosquitto/data/." "$secrets/restored-data"
docker rm "$name" >/dev/null
docker run -d --name "$name" \
  -e MQTT_ALLOW_PLAINTEXT=true \
  -e MQTT_AUTH_POLICY_FILE=/run/secrets/policy.json \
  -v "$secrets:/run/secrets:ro" \
  -v "$secrets/restored-data:/mosquitto/data" \
  "$image" >/dev/null
attempt=0
until [ "$(docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{end}}' "$name")" = "healthy" ]; do
  attempt=$((attempt + 1)); [ "$attempt" -lt 30 ] || { docker logs "$name"; exit 1; }; sleep 1
done
test "$(docker exec "$name" mosquitto_sub -V mqttv5 -h 127.0.0.1 -u alpha -P alpha-two -t piphi/alpha/retained -C 1 -W 5)" = alpha-state

openssl req -x509 -newkey rsa:2048 -nodes -days 1 -subj '/CN=PiPhi test CA' \
  -keyout "$secrets/ca.key" -out "$secrets/ca.crt" >/dev/null 2>&1
openssl req -newkey rsa:2048 -nodes -subj '/CN=127.0.0.1' \
  -keyout "$secrets/server.key" -out "$secrets/server.csr" >/dev/null 2>&1
printf '%s\n' 'subjectAltName=IP:127.0.0.1' 'extendedKeyUsage=serverAuth' > "$secrets/server.ext"
openssl x509 -req -days 1 -in "$secrets/server.csr" -CA "$secrets/ca.crt" -CAkey "$secrets/ca.key" -CAcreateserial \
  -extfile "$secrets/server.ext" -out "$secrets/server.crt" >/dev/null 2>&1
openssl req -newkey rsa:2048 -nodes -subj '/CN=piphi-health' \
  -keyout "$secrets/health-client.key" -out "$secrets/health-client.csr" >/dev/null 2>&1
printf '%s\n' 'extendedKeyUsage=clientAuth' > "$secrets/client.ext"
openssl x509 -req -days 1 -in "$secrets/health-client.csr" -CA "$secrets/ca.crt" -CAkey "$secrets/ca.key" -CAcreateserial \
  -extfile "$secrets/client.ext" -out "$secrets/health-client.crt" >/dev/null 2>&1
chmod 0600 "$secrets/ca.key" "$secrets/server.key" "$secrets/health-client.key"
chmod 0644 "$secrets/ca.crt" "$secrets/server.crt" "$secrets/health-client.crt"
docker rm -f "$name" >/dev/null

docker run -d --name "$name" --restart unless-stopped \
  -e MQTT_USERNAME=piphi \
  -e MQTT_PASSWORD_SECRET_FILE=/run/secrets/password \
  -e MQTT_TLS_ENABLED=true \
  -e MQTT_TLS_CERT_FILE=/run/secrets/server.crt \
  -e MQTT_TLS_KEY_FILE=/run/secrets/server.key \
  -e MQTT_TLS_CA_FILE=/run/secrets/ca.crt \
  -e MQTT_TLS_REQUIRE_CLIENT_CERTIFICATE=true \
  -e MQTT_HEALTH_TLS_CERT_FILE=/run/secrets/health-client.crt \
  -e MQTT_HEALTH_TLS_KEY_FILE=/run/secrets/health-client.key \
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

without_client="$(docker exec "$name" mosquitto_pub -V mqttv5 -h 127.0.0.1 -p 1883 --cafile /run/secrets/ca.crt -u piphi -P smoke-secret -t piphi/mtls -m denied -q 1 2>&1 || true)"
echo "$without_client" | grep -Eq 'certificate required|Protocol error|Connection refused|TLS Error|connection was lost'
docker exec "$name" mosquitto_pub -V mqttv5 -h 127.0.0.1 -p 1883 --cafile /run/secrets/ca.crt \
  --cert /run/secrets/health-client.crt --key /run/secrets/health-client.key \
  -u piphi -P smoke-secret -t piphi/mtls -m accepted -q 1

before_restart="$(docker inspect -f '{{.RestartCount}}' "$name")"
docker exec "$name" /app/docker/tls-admin.sh >/dev/null 2>&1 || true
attempt=0
until [ "$(docker inspect -f '{{.RestartCount}}' "$name")" -gt "$before_restart" ]; do
  attempt=$((attempt + 1)); [ "$attempt" -lt 20 ] || { docker logs "$name"; exit 1; }; sleep 1
done
attempt=0
until [ "$(docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{end}}' "$name")" = "healthy" ]; do
  attempt=$((attempt + 1)); [ "$attempt" -lt 40 ] || { docker logs "$name"; exit 1; }; sleep 1
done
docker exec "$name" grep -q 'tls-rotation-restart' /mosquitto/log/security-audit.jsonl
