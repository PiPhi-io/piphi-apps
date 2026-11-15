#!/bin/sh
set -eu

umask 027
config_file="${MQTT_CONFIG_OUTPUT:-/mosquitto/config/mosquitto.conf}"
password_file="${MQTT_PASSWORD_FILE:-/mosquitto/config/passwordfile}"
password_candidate="${password_file}.candidate"

cleanup() {
  rm -f "$password_candidate" "${config_file}.candidate"
}
trap cleanup EXIT HUP INT TERM

MQTT_CONFIG_OUTPUT="${config_file}.candidate" node /app/dist/src/cli.js
[ -f "$password_candidate" ] || { echo "Password candidate was not generated" >&2; exit 1; }
mosquitto_passwd -U "$password_candidate"
chown mosquitto:mosquitto "$password_candidate"
chmod 0640 "$password_candidate"
mv -f "$password_candidate" "$password_file"

for path in /mosquitto/config /mosquitto/data /mosquitto/log; do
  mkdir -p "$path"
  chown -R mosquitto:mosquitto "$path" 2>/dev/null || {
    echo "warning: unable to update ownership for $path" >&2
  }
done

mosquitto -c "${config_file}.candidate" &
validation_pid=$!
sleep 1
if ! kill -0 "$validation_pid" 2>/dev/null; then
  wait "$validation_pid"
  exit 1
fi
kill -TERM "$validation_pid"
wait "$validation_pid"
mv -f "${config_file}.candidate" "$config_file"
trap - EXIT HUP INT TERM
exec mosquitto -c "$config_file"
