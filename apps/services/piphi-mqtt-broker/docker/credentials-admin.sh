#!/bin/sh
set -eu

umask 027
password_file="${MQTT_PASSWORD_FILE:-/mosquitto/config/passwordfile}"
password_candidate="${password_file}.candidate"
acl_file="${MQTT_ACL_FILE:-/mosquitto/config/aclfile}"
acl_candidate="${acl_file}.candidate"
audit_file="${MQTT_SECURITY_AUDIT_FILE:-/mosquitto/log/security-audit.jsonl}"
action="reload"
[ "${1:-}" = "--disconnect-existing" ] && action="reload-and-disconnect"

cleanup() {
  rm -f "$password_candidate" "$acl_candidate" "${password_file}.previous" "${acl_file}.previous"
}
trap cleanup EXIT HUP INT TERM

node /app/dist/src/cli.js --credentials-only
mosquitto_passwd -U "$password_candidate"
chown mosquitto:mosquitto "$password_candidate" "$acl_candidate"
chmod 0640 "$password_candidate" "$acl_candidate"
cp -p "$password_file" "${password_file}.previous"
cp -p "$acl_file" "${acl_file}.previous"
mv -f "$password_candidate" "$password_file"
mv -f "$acl_candidate" "$acl_file"

if [ "$action" = "reload-and-disconnect" ]; then
  printf '{"timestamp":"%s","action":"%s","result":"applied"}\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$action" >> "$audit_file"
  chmod 0640 "$audit_file"
  rm -f "${password_file}.previous" "${acl_file}.previous"
  trap - EXIT HUP INT TERM
  kill -TERM 1
else
  if ! kill -HUP 1; then
    mv -f "${password_file}.previous" "$password_file"
    mv -f "${acl_file}.previous" "$acl_file"
    exit 1
  fi
  printf '{"timestamp":"%s","action":"%s","result":"applied"}\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$action" >> "$audit_file"
  chmod 0640 "$audit_file"
  rm -f "${password_file}.previous" "${acl_file}.previous"
  trap - EXIT HUP INT TERM
fi
