import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const app = JSON.parse(readFileSync(new URL("../piphi-app.json", import.meta.url), "utf8"));
const manifest = JSON.parse(readFileSync(new URL("../src/manifest.json", import.meta.url), "utf8"));
const packageJson = JSON.parse(readFileSync(new URL("../package.json", import.meta.url), "utf8"));
const packageLock = JSON.parse(readFileSync(new URL("../package-lock.json", import.meta.url), "utf8"));
const catalog = JSON.parse(readFileSync(new URL("../capability-catalog.json", import.meta.url), "utf8"));
const dockerfile = readFileSync(new URL("../Dockerfile", import.meta.url), "utf8");
const entrypoint = readFileSync(new URL("../docker/entrypoint.sh", import.meta.url), "utf8");

test("release metadata and GHCR image stay aligned", () => {
  const releasePackage = app.packages[0];
  const version = releasePackage.version;
  const image = `ghcr.io/piphi-io/mqtt-broker:${version}`;

  assert.equal(app.ci.enforcement, "full");
  assert.equal(app.ci.build_container, true);
  assert.equal(packageJson.version, version);
  assert.equal(packageLock.version, version);
  assert.equal(packageLock.packages[""].version, version);
  assert.equal(manifest.version, version);
  assert.equal(catalog.release, version);
  assert.equal(manifest.runtime.linux.container.image, image);
  assert.equal(manifest.runtime.linux.health.type, "container");
  assert.deepEqual(manifest.runtime.linux.container.environment, {
    MQTT_ALLOW_PLAINTEXT: "false",
    MQTT_TLS_ENABLED: "true",
    MQTT_TLS_REQUIRE_CLIENT_CERTIFICATE: "true",
  });
  assert.equal(manifest.config.schema.properties.allow_plaintext.default, false);
  assert.equal(manifest.config.schema.properties.tls_enabled.default, true);
  assert.equal(manifest.config.schema.properties.tls_require_client_certificate.default, true);
  assert.deepEqual(manifest.config.schema.required, [
    "listener_port",
    "auth_policy_file",
    "tls_ca_file",
    "tls_cert_file",
    "tls_key_file",
    "health_tls_cert_file",
    "health_tls_key_file",
  ]);
  assert.deepEqual(manifest.runtime.linux.container.volumes.at(-1), {
    host: "/var/lib/piphi/mqtt/secrets",
    container: "/run/secrets",
    read_only: true,
  });
  assert.deepEqual(releasePackage.publishing.primary, {
    registry: "ghcr.io",
    repository: "piphi-io/mqtt-broker",
  });
});

test("image labels provenance and drops broker privileges", () => {
  assert.match(dockerfile, /org\.opencontainers\.image\.source="\$\{SOURCE_REPOSITORY\}"/);
  assert.match(dockerfile, /org\.opencontainers\.image\.revision="\$\{SOURCE_REVISION\}"/);
  assert.match(dockerfile, /org\.opencontainers\.image\.version="\$\{RELEASE_VERSION\}"/);
  assert.match(entrypoint, /exec su-exec mosquitto:mosquitto mosquitto -c "\$config_file"/);
});
