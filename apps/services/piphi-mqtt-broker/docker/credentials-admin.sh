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
. /app/docker/identity-transaction.sh

cleanup() {
  identity_cleanup
}
trap cleanup EXIT HUP INT TERM

node /app/dist/src/cli.js --credentials-only
mosquitto_passwd -U "$password_candidate"
chown mosquitto:mosquitto "$password_candidate" "$acl_candidate"
chmod 0640 "$password_candidate" "$acl_candidate"
identity_install_candidates

if [ "$action" = "reload-and-disconnect" ]; then
  if ! kill -TERM 1; then
    identity_rollback
    exit 1
  fi
  identity_commit
  printf '{"timestamp":"%s","action":"%s","result":"applied"}\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$action" >> "$audit_file"
  chmod 0640 "$audit_file"
  trap - EXIT HUP INT TERM
else
  if ! kill -HUP 1; then
    identity_rollback
    exit 1
  fi
  if [ "${PIPHI_TEST_FAIL_IDENTITY_STEP:-}" = "after-reload" ]; then
    identity_rollback
    kill -HUP 1 || true
    exit 1
  fi
  printf '{"timestamp":"%s","action":"%s","result":"applied"}\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$action" >> "$audit_file"
  chmod 0640 "$audit_file"
  identity_commit
  trap - EXIT HUP INT TERM
fi
