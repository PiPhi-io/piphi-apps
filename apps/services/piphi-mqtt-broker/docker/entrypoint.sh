#!/bin/sh
set -eu

node /app/dist/src/cli.js

if [ -n "${MQTT_USERNAME:-}" ] && [ -n "${MQTT_PASSWORD:-}" ]; then
  password_file="${MQTT_PASSWORD_FILE:-/mosquitto/config/passwordfile}"
  mkdir -p "$(dirname "$password_file")"
  mosquitto_passwd -b -c "$password_file" "$MQTT_USERNAME" "$MQTT_PASSWORD"

  if id mosquitto >/dev/null 2>&1; then
    chown mosquitto:mosquitto "$password_file"
    chmod 0640 "$password_file"
  else
    chmod 0644 "$password_file"
  fi
fi

if id mosquitto >/dev/null 2>&1; then
  for path in /mosquitto/config /mosquitto/data /mosquitto/log; do
    mkdir -p "$path"
    chown -R mosquitto:mosquitto "$path" 2>/dev/null || {
      echo "warning: unable to update ownership for $path" >&2
    }
  done
fi

exec mosquitto -c "${MQTT_CONFIG_OUTPUT:-/mosquitto/config/mosquitto.conf}"
