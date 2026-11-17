#!/bin/sh
set -eu

umask 027
config_file="${MQTT_CONFIG_OUTPUT:-/mosquitto/config/mosquitto.conf}"
password_file="${MQTT_PASSWORD_FILE:-/mosquitto/config/passwordfile}"
password_candidate="${password_file}.candidate"
acl_file="${MQTT_ACL_FILE:-/mosquitto/config/aclfile}"
acl_candidate="${acl_file}.candidate"
. /app/docker/identity-transaction.sh

cleanup() {
  identity_cleanup
  rm -f "${config_file}.candidate"
}
trap cleanup EXIT HUP INT TERM

if [ "${MQTT_TLS_ENABLED:-false}" = "true" ]; then
  tls_dir=/mosquitto/config/tls
  mkdir -p "$tls_dir"
  export MQTT_TLS_SOURCE_CERT_FILE="${MQTT_TLS_CERT_FILE:?MQTT_TLS_CERT_FILE is required}"
  export MQTT_TLS_SOURCE_KEY_FILE="${MQTT_TLS_KEY_FILE:?MQTT_TLS_KEY_FILE is required}"
  cp "$MQTT_TLS_SOURCE_CERT_FILE" "$tls_dir/server.crt"
  cp "$MQTT_TLS_SOURCE_KEY_FILE" "$tls_dir/server.key"
  export MQTT_TLS_CERT_FILE="$tls_dir/server.crt"
  export MQTT_TLS_KEY_FILE="$tls_dir/server.key"
  if [ -n "${MQTT_TLS_CA_FILE:-}" ]; then
    export MQTT_TLS_SOURCE_CA_FILE="$MQTT_TLS_CA_FILE"
    cp "$MQTT_TLS_SOURCE_CA_FILE" "$tls_dir/ca.crt"
    export MQTT_TLS_CA_FILE="$tls_dir/ca.crt"
  fi
  chown -R mosquitto:mosquitto "$tls_dir"
  chmod 0750 "$tls_dir"
  chmod 0640 "$tls_dir"/*
fi

MQTT_CONFIG_OUTPUT="${config_file}.candidate" node /app/dist/src/cli.js
[ -f "$password_candidate" ] || { echo "Password candidate was not generated" >&2; exit 1; }
[ -f "$acl_candidate" ] || { echo "ACL candidate was not generated" >&2; exit 1; }
mosquitto_passwd -U "$password_candidate"
chown mosquitto:mosquitto "$password_candidate" "$acl_candidate"
chmod 0640 "$password_candidate" "$acl_candidate"
identity_install_candidates

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
identity_commit
trap - EXIT HUP INT TERM
exec mosquitto -c "$config_file"
