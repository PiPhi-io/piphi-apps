#!/bin/sh
set -eu

image="piphi-mqtt-broker:smoke"
name="piphi-mqtt-smoke-$$"
failure_name="${name}-entry-failure"
secrets="${TMPDIR:-/tmp}/piphi-mqtt-smoke-$$"

cleanup() {
  docker rm -f "$name" >/dev/null 2>&1 || true
  docker rm -f "$failure_name" >/dev/null 2>&1 || true
  if [ -d "$secrets" ]; then
    docker run --rm --entrypoint sh -v "$secrets:/cleanup" "$image" -c 'chmod -R 0777 /cleanup' >/dev/null 2>&1 || true
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
docker exec "$name" chmod 0555 /mosquitto/data
docker exec "$name" node /app/dist/src/healthcheck.js --liveness
if docker exec "$name" node /app/dist/src/healthcheck.js --readiness >/dev/null 2>&1; then
  echo "Persistence readiness passed without Mosquitto write access" >&2
  exit 1
fi
docker exec "$name" chmod 0755 /mosquitto/data
docker exec "$name" chown mosquitto:mosquitto /mosquitto/data
docker exec "$name" node /app/dist/src/healthcheck.js --readiness

docker exec "$name" sh -ec '
  mosquitto_sub -V mqttv5 -h 127.0.0.1 -u piphi -P smoke-secret -t piphi/test -C 1 -W 5 > /tmp/message &
  subscriber=$!
  sleep 1
  mosquitto_pub -V mqttv5 -h 127.0.0.1 -u piphi -P smoke-secret -t piphi/test -m ok -q 1
  wait "$subscriber"
  test "$(cat /tmp/message)" = ok
  ! grep -q smoke-secret /mosquitto/config/identity/current/passwordfile
  test "$(stat -c %a /mosquitto/config/identity/current/passwordfile)" = 640
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

ln -s /etc/hostname "$secrets/escaped-password"
ln -s /etc/hostname "$secrets/escaped-policy"
sed 's#/run/secrets/alpha-password#/run/secrets/escaped-password#' "$secrets/policy.json" > "$secrets/policy-escape.json"
if docker exec -e MQTT_AUTH_POLICY_FILE=/run/secrets/policy-escape.json "$name" node /app/dist/src/cli.js --credentials-only >/dev/null 2>&1; then
  echo "Resolved password path escaped its secret directory" >&2
  exit 1
fi
if docker exec -e MQTT_AUTH_POLICY_FILE=/run/secrets/escaped-policy "$name" node /app/dist/src/cli.js --validate-paths >/dev/null 2>&1; then
  echo "Resolved auth policy path escaped its secret directory" >&2
  exit 1
fi

for failure_step in before-pointer-swap after-pointer-swap after-reload; do
  active_password_hash="$(docker exec "$name" sha256sum /mosquitto/config/identity/current/passwordfile | cut -d' ' -f1)"
  active_acl_hash="$(docker exec "$name" sha256sum /mosquitto/config/identity/current/aclfile | cut -d' ' -f1)"
  printf '%s' 'alpha-three' > "$secrets/alpha-password"
  if docker exec -e PIPHI_TEST_FAIL_IDENTITY_STEP="$failure_step" "$name" /app/docker/credentials-admin.sh >/dev/null 2>&1; then
    echo "Injected identity transaction failure was accepted" >&2
    exit 1
  fi
  sleep 1
  test "$(docker exec "$name" sha256sum /mosquitto/config/identity/current/passwordfile | cut -d' ' -f1)" = "$active_password_hash"
  test "$(docker exec "$name" sha256sum /mosquitto/config/identity/current/aclfile | cut -d' ' -f1)" = "$active_acl_hash"
  docker exec "$name" mosquitto_pub -V mqttv5 -h 127.0.0.1 -u alpha -P alpha-two -t piphi/alpha/rollback -m rollback-ok -q 1
  rejected_candidate="$(docker exec "$name" mosquitto_pub -V mqttv5 -h 127.0.0.1 -u alpha -P alpha-three -t piphi/alpha/rollback -m denied -q 1 2>&1 || true)"
  echo "$rejected_candidate" | grep -q 'Not authorized'
  printf '%s' 'alpha-two' > "$secrets/alpha-password"
done

generation_count_before="$(docker exec "$name" find /mosquitto/config/identity/generations -mindepth 1 -maxdepth 1 -type d | wc -l)"
printf '%s' 'alpha-three' > "$secrets/alpha-password"
docker exec -e PIPHI_TEST_HARD_CRASH_AFTER_IDENTITY_SWAP=true "$name" /app/docker/credentials-admin.sh >/dev/null 2>&1 || true
docker exec "$name" test -f /mosquitto/config/identity/transaction.json
printf '%s' 'alpha-two' > "$secrets/alpha-password"
docker restart "$name" >/dev/null
attempt=0
until [ "$(docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{end}}' "$name")" = "healthy" ]; do
  attempt=$((attempt + 1)); [ "$attempt" -lt 40 ] || { docker logs "$name"; exit 1; }; sleep 1
done
docker exec "$name" test ! -f /mosquitto/config/identity/transaction.json
test "$(docker exec "$name" find /mosquitto/config/identity/generations -mindepth 1 -maxdepth 1 -type d | wc -l)" -gt "$generation_count_before"
docker exec "$name" mosquitto_pub -V mqttv5 -h 127.0.0.1 -u alpha -P alpha-two -t piphi/alpha/recovered-restart -m recovered -q 1

mkdir -p "$secrets/entry-config"
docker cp "$name:/mosquitto/config/identity" "$secrets/entry-config/identity"
password_before="$(sha256sum "$secrets/entry-config/identity/current/passwordfile" | cut -d' ' -f1)"
acl_before="$(sha256sum "$secrets/entry-config/identity/current/aclfile" | cut -d' ' -f1)"
docker run -d --name "$failure_name" \
  -e MQTT_ALLOW_PLAINTEXT=true \
  -e MQTT_AUTH_POLICY_FILE=/run/secrets/policy.json \
  -e PIPHI_TEST_FAIL_IDENTITY_STEP=after-pointer-swap \
  -v "$secrets:/run/secrets:ro" \
  -v "$secrets/entry-config:/mosquitto/config" \
  "$image" >/dev/null
failure_status="$(docker wait "$failure_name")"
test "$failure_status" -ne 0
test "$(sha256sum "$secrets/entry-config/identity/current/passwordfile" | cut -d' ' -f1)" = "$password_before"
test "$(sha256sum "$secrets/entry-config/identity/current/aclfile" | cut -d' ' -f1)" = "$acl_before"
docker rm "$failure_name" >/dev/null

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

ln -s /etc/hostname "$secrets/escaped-tls"
for confined_field in MQTT_TLS_CA_FILE MQTT_TLS_CERT_FILE MQTT_TLS_KEY_FILE MQTT_HEALTH_TLS_CERT_FILE MQTT_HEALTH_TLS_KEY_FILE; do
  if docker exec -e "$confined_field=/run/secrets/escaped-tls" "$name" node /app/dist/src/cli.js --validate-paths >/dev/null 2>&1; then
    echo "Resolved TLS path escaped its secret directory" >&2
    exit 1
  fi
done

openssl genpkey -algorithm RSA -pkeyopt rsa_keygen_bits:2048 -out "$secrets/other.key" >/dev/null 2>&1
openssl req -x509 -new -key "$secrets/other.key" -days 1 -subj '/CN=Other test CA' -out "$secrets/other-ca.crt" >/dev/null 2>&1
openssl req -new -key "$secrets/other.key" -subj '/CN=127.0.0.1' -out "$secrets/other-server.csr" >/dev/null 2>&1
openssl x509 -req -days 1 -in "$secrets/other-server.csr" -CA "$secrets/other-ca.crt" -CAkey "$secrets/other.key" -CAcreateserial \
  -extfile "$secrets/server.ext" -out "$secrets/other-server.crt" >/dev/null 2>&1
openssl x509 -req -days 0 -in "$secrets/server.csr" -CA "$secrets/ca.crt" -CAkey "$secrets/ca.key" -CAcreateserial \
  -extfile "$secrets/server.ext" -out "$secrets/expired-server.crt" >/dev/null 2>&1
chmod 0600 "$secrets/other.key"
chmod 0644 "$secrets/other-ca.crt" "$secrets/other-server.crt" "$secrets/expired-server.crt"

negative_restart_count="$(docker inspect -f '{{.RestartCount}}' "$name")"
for negative_case in \
  'MQTT_TLS_KEY_FILE=/run/secrets/other.key' \
  'MQTT_TLS_CERT_FILE=/run/secrets/other-server.crt' \
  'MQTT_TLS_CERT_FILE=/run/secrets/expired-server.crt' \
  'MQTT_HEALTH_TLS_KEY_FILE=/run/secrets/other.key'; do
  env_name="${negative_case%%=*}"
  env_value="${negative_case#*=}"
  if docker exec -e "$env_name=$env_value" "$name" /app/docker/tls-admin.sh >/dev/null 2>&1; then
    echo "Invalid TLS rotation material was accepted" >&2
    exit 1
  fi
  test "$(docker inspect -f '{{.RestartCount}}' "$name")" = "$negative_restart_count"
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
