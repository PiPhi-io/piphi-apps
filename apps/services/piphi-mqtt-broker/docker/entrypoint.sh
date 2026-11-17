#!/bin/sh
set -eu

umask 027
config_file="${MQTT_CONFIG_OUTPUT:-/mosquitto/config/mosquitto.conf}"
identity_root="${MQTT_IDENTITY_ROOT:-/mosquitto/config/identity}"
export MQTT_IDENTITY_CANDIDATE_DIR="${identity_root}/candidate-entrypoint-$$"
password_candidate="${MQTT_IDENTITY_CANDIDATE_DIR}/passwordfile"
acl_candidate="${MQTT_IDENTITY_CANDIDATE_DIR}/aclfile"

cleanup() {
  node /app/dist/src/cli.js --rollback-identity >/dev/null 2>&1 || true
  node /app/dist/src/cli.js --recover-identity >/dev/null 2>&1 || true
  rm -rf "$MQTT_IDENTITY_CANDIDATE_DIR"
  rm -f "${config_file}.candidate"
}
trap cleanup EXIT HUP INT TERM

node /app/dist/src/cli.js --validate-paths

if [ "${MQTT_TLS_ENABLED:-false}" = "true" ]; then
  tls_dir=/mosquitto/config/tls
  mkdir -p "$tls_dir"
  export MQTT_TLS_SOURCE_CERT_FILE="$(realpath "${MQTT_TLS_CERT_FILE:?MQTT_TLS_CERT_FILE is required}")"
  export MQTT_TLS_SOURCE_KEY_FILE="$(realpath "${MQTT_TLS_KEY_FILE:?MQTT_TLS_KEY_FILE is required}")"
  cp "$MQTT_TLS_SOURCE_CERT_FILE" "$tls_dir/server.crt"
  cp "$MQTT_TLS_SOURCE_KEY_FILE" "$tls_dir/server.key"
  export MQTT_TLS_CERT_FILE="$tls_dir/server.crt"
  export MQTT_TLS_KEY_FILE="$tls_dir/server.key"
  if [ -n "${MQTT_TLS_CA_FILE:-}" ]; then
    export MQTT_TLS_SOURCE_CA_FILE="$(realpath "$MQTT_TLS_CA_FILE")"
    cp "$MQTT_TLS_SOURCE_CA_FILE" "$tls_dir/ca.crt"
    export MQTT_TLS_CA_FILE="$tls_dir/ca.crt"
  fi
  chown -R mosquitto:mosquitto "$tls_dir"
  chmod 0750 "$tls_dir"
  chmod 0640 "$tls_dir"/*
fi

node /app/dist/src/cli.js --recover-identity
MQTT_CONFIG_OUTPUT="${config_file}.candidate" node /app/dist/src/cli.js
[ -f "$password_candidate" ] || { echo "Password candidate was not generated" >&2; exit 1; }
[ -f "$acl_candidate" ] || { echo "ACL candidate was not generated" >&2; exit 1; }
mosquitto_passwd -U "$password_candidate"
chown mosquitto:mosquitto "$MQTT_IDENTITY_CANDIDATE_DIR" "$password_candidate" "$acl_candidate"
chmod 0640 "$password_candidate" "$acl_candidate"
if [ "${PIPHI_TEST_FAIL_IDENTITY_STEP:-}" = "before-pointer-swap" ]; then exit 1; fi
node /app/dist/src/cli.js --activate-identity
if [ "${PIPHI_TEST_FAIL_IDENTITY_STEP:-}" = "after-pointer-swap" ]; then exit 1; fi

for path in /mosquitto/config /mosquitto/data /mosquitto/log; do
  mkdir -p "$path"
  chown -R mosquitto:mosquitto "$path" 2>/dev/null || {
    echo "warning: unable to update ownership for $path" >&2
  }
done

mosquitto -c "${config_file}.candidate" &
validation_pid=$!
attempt=0
until node /app/dist/src/healthcheck.js --startup >/dev/null 2>&1; do
  attempt=$((attempt + 1))
  if [ "$attempt" -ge 10 ] || ! kill -0 "$validation_pid" 2>/dev/null; then
    wait "$validation_pid" 2>/dev/null || true
    echo "Broker startup qualification failed" >&2
    exit 1
  fi
  sleep 1
done
kill -TERM "$validation_pid"
wait "$validation_pid"
mv -f "${config_file}.candidate" "$config_file"
node /app/dist/src/cli.js --commit-identity
trap - EXIT HUP INT TERM
exec mosquitto -c "$config_file"
