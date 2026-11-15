#!/bin/sh
set -eu

umask 027
password_file="${MQTT_PASSWORD_FILE:-/mosquitto/config/passwordfile}"
password_candidate="${password_file}.candidate"
audit_file="${MQTT_SECURITY_AUDIT_FILE:-/mosquitto/log/security-audit.jsonl}"
action="reload"
[ "${1:-}" = "--disconnect-existing" ] && action="reload-and-disconnect"

cleanup() {
  rm -f "$password_candidate"
}
trap cleanup EXIT HUP INT TERM

node /app/dist/src/cli.js --credentials-only
mosquitto_passwd -U "$password_candidate"
chown mosquitto:mosquitto "$password_candidate" "${MQTT_ACL_FILE:-/mosquitto/config/aclfile}"
chmod 0640 "$password_candidate" "${MQTT_ACL_FILE:-/mosquitto/config/aclfile}"
mv -f "$password_candidate" "$password_file"
printf '{"timestamp":"%s","action":"%s","result":"applied"}\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$action" >> "$audit_file"
chmod 0640 "$audit_file"

trap - EXIT HUP INT TERM
if [ "$action" = "reload-and-disconnect" ]; then
  kill -TERM 1
else
  kill -HUP 1
fi
