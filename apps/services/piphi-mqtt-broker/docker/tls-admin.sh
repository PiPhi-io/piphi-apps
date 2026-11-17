#!/bin/sh
set -eu

audit_file="${MQTT_SECURITY_AUDIT_FILE:-/mosquitto/log/security-audit.jsonl}"

[ "${MQTT_TLS_ENABLED:-false}" = "true" ] || { echo "TLS is not enabled" >&2; exit 1; }
node /app/dist/src/cli.js --validate-paths
source_cert_file="${MQTT_TLS_SOURCE_CERT_FILE:-${MQTT_TLS_CERT_FILE:-}}"
source_key_file="${MQTT_TLS_SOURCE_KEY_FILE:-${MQTT_TLS_KEY_FILE:-}}"
: "${source_cert_file:?MQTT_TLS_CERT_FILE is required}"
: "${source_key_file:?MQTT_TLS_KEY_FILE is required}"
source_ca_file="${MQTT_TLS_SOURCE_CA_FILE:-${MQTT_TLS_CA_FILE:-}}"
source_cert_file="$(realpath "$source_cert_file")"
source_key_file="$(realpath "$source_key_file")"
if [ -n "$source_ca_file" ]; then source_ca_file="$(realpath "$source_ca_file")"; fi

cert_digest="$(openssl x509 -in "$source_cert_file" -pubkey -noout | sha256sum | cut -d' ' -f1)"
key_digest="$(openssl pkey -in "$source_key_file" -pubout | sha256sum | cut -d' ' -f1)"
[ "$cert_digest" = "$key_digest" ] || { echo "TLS certificate and key do not match" >&2; exit 1; }
openssl x509 -in "$source_cert_file" -checkend 1 -noout >/dev/null
if [ -n "$source_ca_file" ]; then
  openssl verify -CAfile "$source_ca_file" "$source_cert_file" >/dev/null
fi

if [ "${MQTT_TLS_REQUIRE_CLIENT_CERTIFICATE:-false}" = "true" ]; then
  : "${source_ca_file:?MQTT_TLS_CA_FILE is required for mTLS}"
  : "${MQTT_HEALTH_TLS_CERT_FILE:?MQTT_HEALTH_TLS_CERT_FILE is required for mTLS}"
  : "${MQTT_HEALTH_TLS_KEY_FILE:?MQTT_HEALTH_TLS_KEY_FILE is required for mTLS}"
  openssl verify -CAfile "$source_ca_file" "$MQTT_HEALTH_TLS_CERT_FILE" >/dev/null
  health_cert_digest="$(openssl x509 -in "$MQTT_HEALTH_TLS_CERT_FILE" -pubkey -noout | sha256sum | cut -d' ' -f1)"
  health_key_digest="$(openssl pkey -in "$MQTT_HEALTH_TLS_KEY_FILE" -pubout | sha256sum | cut -d' ' -f1)"
  [ "$health_cert_digest" = "$health_key_digest" ] || { echo "Health TLS certificate and key do not match" >&2; exit 1; }
fi

printf '{"timestamp":"%s","action":"tls-rotation-restart","result":"validated"}\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" >> "$audit_file"
chmod 0640 "$audit_file"
sync "$audit_file"
kill -TERM 1
