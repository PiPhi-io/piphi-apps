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

audit() {
  result="$1"
  mkdir -p "$(dirname "$audit_file")"
  printf '{"timestamp":"%s","action":"%s","result":"%s"}\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$action" "$result" >> "$audit_file"
  chmod 0640 "$audit_file"
  sync "$audit_file"
}

cleanup() {
  node /app/dist/src/cli.js --rollback-identity >/dev/null 2>&1 || true
  node /app/dist/src/cli.js --recover-identity >/dev/null 2>&1 || true
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
  audit "restart-requested"
  if ! kill -TERM 1; then
    node /app/dist/src/cli.js --rollback-identity
    audit "restart-failed-rolled-back"
    exit 1
  fi
  node /app/dist/src/cli.js --commit-identity
  trap - EXIT HUP INT TERM
else
  audit "reload-requested"
  if ! kill -HUP 1; then
    node /app/dist/src/cli.js --rollback-identity
    audit "reload-failed-rolled-back"
    exit 1
  fi
  attempt=0
  until node /app/dist/src/healthcheck.js --readiness >/dev/null 2>&1; do
    attempt=$((attempt + 1))
    if [ "$attempt" -ge 5 ]; then
      node /app/dist/src/cli.js --rollback-identity
      kill -HUP 1 || true
      audit "reload-not-ready-rolled-back"
      exit 1
    fi
    sleep 1
  done
  if [ "${PIPHI_TEST_FAIL_IDENTITY_STEP:-}" = "after-reload" ]; then
    node /app/dist/src/cli.js --rollback-identity
    kill -HUP 1 || true
    audit "reload-injected-failure-rolled-back"
    exit 1
  fi
  node /app/dist/src/cli.js --commit-identity
  audit "applied"
  trap - EXIT HUP INT TERM
fi
