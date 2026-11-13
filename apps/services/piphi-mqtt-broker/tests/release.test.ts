import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const app = JSON.parse(readFileSync(new URL("../piphi-app.json", import.meta.url), "utf8"));
const manifest = JSON.parse(readFileSync(new URL("../src/manifest.json", import.meta.url), "utf8"));
const packageJson = JSON.parse(readFileSync(new URL("../package.json", import.meta.url), "utf8"));

test("release metadata and GHCR image stay aligned", () => {
  const releasePackage = app.packages[0];
  const version = releasePackage.version;
  const image = `ghcr.io/piphi-io/mqtt-broker:${version}`;

  assert.equal(app.ci.enforcement, "full");
  assert.equal(app.ci.build_container, true);
  assert.equal(packageJson.version, version);
  assert.equal(manifest.version, version);
  assert.equal(manifest.runtime.linux.container.image, image);
  assert.deepEqual(releasePackage.publishing.primary, {
    registry: "ghcr.io",
    repository: "piphi-io/mqtt-broker",
  });
});
