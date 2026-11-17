#!/bin/sh
set -eu

umask 027
identity_root="${MQTT_IDENTITY_ROOT:-/mosquitto/config/identity}"
export MQTT_IDENTITY_CANDIDATE_DIR="${identity_root}/candidate-admin-$$"
password_candidate="${MQTT_IDENTITY_CANDIDATE_DIR}/passwordfile"
acl_candidate="${MQTT_IDENTITY_CANDIDATE_DIR}/aclfile"
audit_file="${MQTT_SECURITY_AUDIT_FILE:-/mosquitto/log/security-audit.jsonl}"
action="reload"
[ "${1:-}" = "--disconnect-existing" ] && action="reload-and-disconnect"

cleanup() {
  node /app/dist/src/cli.js --rollback-identity >/dev/null 2>&1 || true
  rm -rf "$MQTT_IDENTITY_CANDIDATE_DIR"
}
trap cleanup EXIT HUP INT TERM

node /app/dist/src/cli.js --validate-paths
node /app/dist/src/cli.js --recover-identity
node /app/dist/src/cli.js --credentials-only
mosquitto_passwd -U "$password_candidate"
chown mosquitto:mosquitto "$MQTT_IDENTITY_CANDIDATE_DIR" "$password_candidate" "$acl_candidate"
chmod 0640 "$password_candidate" "$acl_candidate"
if [ "${PIPHI_TEST_FAIL_IDENTITY_STEP:-}" = "before-pointer-swap" ]; then exit 1; fi
node /app/dist/src/cli.js --activate-identity
if [ "${PIPHI_TEST_HARD_CRASH_AFTER_IDENTITY_SWAP:-}" = "true" ]; then kill -KILL $$; fi
if [ "${PIPHI_TEST_FAIL_IDENTITY_STEP:-}" = "after-pointer-swap" ]; then exit 1; fi

if [ "$action" = "reload-and-disconnect" ]; then
  if ! kill -TERM 1; then
    node /app/dist/src/cli.js --rollback-identity
    exit 1
  fi
  node /app/dist/src/cli.js --commit-identity
  printf '{"timestamp":"%s","action":"%s","result":"applied"}\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$action" >> "$audit_file"
  chmod 0640 "$audit_file"
  trap - EXIT HUP INT TERM
else
  if ! kill -HUP 1; then
    node /app/dist/src/cli.js --rollback-identity
    exit 1
  fi
  if [ "${PIPHI_TEST_FAIL_IDENTITY_STEP:-}" = "after-reload" ]; then
    node /app/dist/src/cli.js --rollback-identity
    kill -HUP 1 || true
    exit 1
  fi
  printf '{"timestamp":"%s","action":"%s","result":"applied"}\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$action" >> "$audit_file"
  chmod 0640 "$audit_file"
  node /app/dist/src/cli.js --commit-identity
  trap - EXIT HUP INT TERM
fi
