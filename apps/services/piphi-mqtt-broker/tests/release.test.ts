import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const app = JSON.parse(readFileSync(new URL("../piphi-app.json", import.meta.url), "utf8"));
const manifest = JSON.parse(readFileSync(new URL("../src/manifest.json", import.meta.url), "utf8"));
const packageJson = JSON.parse(readFileSync(new URL("../package.json", import.meta.url), "utf8"));
const packageLock = JSON.parse(readFileSync(new URL("../package-lock.json", import.meta.url), "utf8"));
const catalog = JSON.parse(readFileSync(new URL("../capability-catalog.json", import.meta.url), "utf8"));

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
  assert.deepEqual(releasePackage.publishing.primary, {
    registry: "ghcr.io",
    repository: "piphi-io/mqtt-broker",
  });
});
