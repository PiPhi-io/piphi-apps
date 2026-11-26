#!/bin/sh
set -eu

action="${1:-check}"
case "$action" in
  check)
    exec node /app/dist/src/diagnostics.js
    ;;
  flush)
    database="${MQTT_PERSISTENCE_LOCATION:-/mosquitto/data/}mosquitto.db"
    before_mtime="$(stat -c %Y "$database" 2>/dev/null || echo 0)"
    sleep 1
    kill -USR1 1
    # The signal is asynchronous. A bounded wait lets Mosquitto finish its
    # persistence write before an orchestrator starts a snapshot.
    attempt=0
    while [ "$attempt" -lt 10 ]; do
      if [ -s "$database" ] && [ "$(stat -c %Y "$database")" -gt "$before_mtime" ]; then
        exec node /app/dist/src/diagnostics.js
      fi
      attempt=$((attempt + 1))
      sleep 1
    done
    echo "Persistence flush did not produce a database" >&2
    exit 1
    ;;
  *)
    echo "usage: storage-admin.sh [check|flush]" >&2
    exit 2
    ;;
esac
