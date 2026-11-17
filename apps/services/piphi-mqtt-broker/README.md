# PiPhi MQTT Broker

`piphi-mqtt-broker` packages Mosquitto as a bounded PiPhi `platform_service`.
Version 0.3.1 binds managed principals to isolated workload namespaces, separates
the mTLS health-client identity from the server identity, adds independently
addressable lifecycle probes, and makes credential/TLS rotation fail closed.

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
      "namespace": "zigbee2mqtt",
      "password_secret_file": "/run/secrets/zigbee2mqtt-password",
      "read": ["piphi/zigbee2mqtt/#"],
      "write": ["piphi/zigbee2mqtt/#"],
      "health": false
    },
    {
      "username": "health",
      "namespace": "_health",
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
  ghcr.io/piphi-io/mqtt-broker:0.3.1
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
  ghcr.io/piphi-io/mqtt-broker:0.3.1
```

Set `MQTT_TLS_REQUIRE_CLIENT_CERTIFICATE=true` for mTLS. Certificates and keys
must be mounted under `/run/secrets/` or `/mosquitto/config/`. Restart the
container after rotating certificates so existing sessions are terminated and
readiness is requalified.

At startup the entrypoint copies the mounted server certificate, key, and CA
into a Mosquitto-owned mode-0640 internal directory. Mounted source keys may
remain root-owned mode 0600; they are never emitted to logs or process arguments.
Connection logging is disabled because upstream connection records include
client identifiers and usernames; operational audit records contain only an
action, result, and timestamp.

For mTLS, mount a dedicated health client identity and set
`MQTT_HEALTH_TLS_CERT_FILE` and `MQTT_HEALTH_TLS_KEY_FILE`; never reuse the
server private key as a client identity. Replace mounted TLS files atomically,
then run `/app/docker/tls-admin.sh`. It verifies certificate/key consistency and
the health-client chain before a restart. The replacement image startup probe
must pass before the container becomes healthy.

### 0.3.0 policy migration

0.3.1 accepts an omitted `namespace` only when every read/write filter clearly
resolves to the same first segment below `MQTT_TOPIC_PREFIX`; this preserves
existing managed clients. Add the explicit field shown above before the next
policy edit. Cross-namespace filters, duplicate namespaces, and non-health use
of `_health` now fail closed. Legacy `MQTT_USERNAME`/password mode remains a
single-trust-domain compatibility path and is not a multi-workload boundary.

## Enforced defaults

| Control | Default |
| --- | ---: |
| Connections | 256 |
| Packet/payload size | 1 MiB |
| Inflight messages | 32 |
| Queued messages | 1,024 |
| Queued bytes | 16 MiB |
| Broker memory | 256 MiB |
| Keepalive | 300 seconds maximum |
| Durable-session expiry | 7 days |

Override these with the corresponding `MQTT_MAX_*`, `MQTT_MEMORY_LIMIT`, and
`MQTT_PERSISTENT_CLIENT_EXPIRATION` variables. Container CPU, memory, and volume
quotas remain the orchestrator's responsibility.

## Health and recovery

The image readiness check performs an authenticated MQTT 5 subscribe/publish
round trip beneath the health namespace and verifies persistence storage is
writable. Startup performs the same qualification against the candidate broker
before atomically promoting its config. An authenticated MQTT CONNECT liveness
probe is available as `node /app/dist/src/healthcheck.js --liveness`; readiness
uses `--readiness`, and startup uses `--startup`. Probe failures never print
credentials, client identifiers, topics, or payloads.

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
