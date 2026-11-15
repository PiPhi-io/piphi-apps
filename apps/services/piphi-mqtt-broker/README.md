# PiPhi MQTT Broker

`piphi-mqtt-broker` packages Mosquitto as a bounded PiPhi `platform_service`.
Version 0.3.0 adds managed workload identities, explicit per-principal ACLs,
audited credential reload/revocation, and automated restore qualification to the
TLS, quota, health, and config hardening introduced in 0.2.0.

## Security boundary

Production deployments use `MQTT_AUTH_POLICY_FILE` to assign every workload a
distinct principal and explicit read/write filters beneath
`MQTT_TOPIC_PREFIX/`. Filters outside the configured prefix and access to
`$SYS`/`$CONTROL` fail validation. No principal receives `#` by default.

Anonymous access is disabled by default. Plain MQTT is also disabled by default
in the image and must be explicitly enabled with `MQTT_ALLOW_PLAINTEXT=true` on
an enforced private container network. Use TLS for every path crossing a host or
trust boundary.

## Credential handling

Mount a policy and one read-only password secret per principal:

```json
{
  "schema_version": 1,
  "principals": [
    {
      "username": "zigbee2mqtt",
      "password_secret_file": "/run/secrets/zigbee2mqtt-password",
      "read": ["piphi/zigbee2mqtt/#"],
      "write": ["piphi/zigbee2mqtt/#"],
      "health": false
    },
    {
      "username": "health",
      "password_secret_file": "/run/secrets/health-password",
      "read": ["piphi/_health/#"],
      "write": ["piphi/_health/#"],
      "health": true
    }
  ]
}
```

```bash
docker run --rm \
  -e MQTT_AUTH_POLICY_FILE=/run/secrets/mqtt-policy.json \
  -e MQTT_ALLOW_PLAINTEXT=true \
  -v ./secrets:/run/secrets:ro \
  ghcr.io/piphi-io/mqtt-broker:0.3.0
```

The entrypoint hashes the password through a mode-0600 temporary file, installs
the password database atomically, and never places the password in a process
argument or generated broker config. `MQTT_PASSWORD` remains a compatibility
fallback for single-principal upgrades and should not be used for shared
production infrastructure.

After atomically replacing policy/secret mounts, reload credentials and ACLs:

```bash
docker exec mqtt-broker /app/docker/credentials-admin.sh
```

Use `--disconnect-existing` for revocation. This terminates the broker so the
orchestrator restarts it and all existing sessions must reauthenticate. Each
operation appends a payload-free record to
`/mosquitto/log/security-audit.jsonl`.

## TLS profile

```bash
docker run --rm -p 8883:1883 \
  -e MQTT_USERNAME=piphi \
  -e MQTT_PASSWORD_SECRET_FILE=/run/secrets/mqtt-password \
  -e MQTT_TLS_ENABLED=true \
  -e MQTT_TLS_CA_FILE=/run/secrets/ca.crt \
  -e MQTT_TLS_CERT_FILE=/run/secrets/server.crt \
  -e MQTT_TLS_KEY_FILE=/run/secrets/server.key \
  -v ./secrets:/run/secrets:ro \
  ghcr.io/piphi-io/mqtt-broker:0.3.0
```

Set `MQTT_TLS_REQUIRE_CLIENT_CERTIFICATE=true` for mTLS. Certificates and keys
must be mounted under `/run/secrets/` or `/mosquitto/config/`. Restart the
container after rotating certificates so existing sessions are terminated and
readiness is requalified.

## Enforced defaults

| Control | Default |
| --- | ---: |
| Connections | 256 |
| Packet/payload size | 1 MiB |
| Inflight messages | 32 |
| Queued messages | 1,024 |
| Queued bytes | 16 MiB |
| Broker memory | 256 MiB |
| Durable-session expiry | 7 days |

Override these with the corresponding `MQTT_MAX_*`, `MQTT_MEMORY_LIMIT`, and
`MQTT_PERSISTENT_CLIENT_EXPIRATION` variables. Container CPU, memory, and volume
quotas remain the orchestrator's responsibility.

## Health and recovery

The image health check performs an authenticated MQTT 5 subscribe/publish
round trip beneath `<prefix>/_health/`. Startup first validates a candidate
configuration by launching Mosquitto, then atomically promotes it.

Back up `/mosquitto/config` and `/mosquitto/data` together after a clean stop.
Keep mounted TLS/password secret sources in the same encrypted backup set. To
restore, stop the broker, restore all three sets from the same snapshot, verify
ownership (`mosquitto:mosquitto`, files no broader than `0640`), and start the
same image version before upgrading. The container suite restores retained data
into a fresh broker container and requalifies current authorization. Power-loss,
disk-full, corruption, encrypted-backup integration, and cross-version restore
remain operator qualification items.

## Development and release

```bash
npm ci
npm audit --omit=dev --audit-level=high
npm test
npm run build
sh tests/container-smoke.sh
```

The monorepo `Release one app package` workflow publishes amd64/arm64 images,
SBOM and provenance attestations, immutable release evidence, and a registry
cutover proposal.
