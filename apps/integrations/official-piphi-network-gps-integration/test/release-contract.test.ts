import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { resolve } from "node:path";
import test from "node:test";

const root = resolve(import.meta.dirname, "../..");

test("release metadata stays aligned at 1.1.3", async () => {
  const packageJson = JSON.parse(await readFile(resolve(root, "package.json"), "utf8")) as {
    version: string;
  };
  const app = JSON.parse(await readFile(resolve(root, "piphi-app.json"), "utf8")) as {
    packages: Array<{ version: string }>;
  };
  const manifest = JSON.parse(await readFile(resolve(root, "src/manifest.json"), "utf8")) as {
    version: string;
    image: string;
    runtime: { linux: { container: { image: string; privileged: boolean } } };
  };
  assert.equal(packageJson.version, "1.1.3");
  assert.equal(app.packages[0]?.version, packageJson.version);
  assert.equal(manifest.version, packageJson.version);
  assert.equal(manifest.image, "ghcr.io/piphi-io/official-gps-integration:1.1.3");
  assert.equal(manifest.runtime.linux.container.image, manifest.image);
  assert.equal(manifest.runtime.linux.container.privileged, false);
});

test("container is pinned, locked, health checked, non-root, and stateful", async () => {
  const dockerfile = await readFile(resolve(root, "dockerfile"), "utf8");
  assert.match(dockerfile, /FROM node:22-bookworm-slim@sha256:/);
  assert.match(dockerfile, /pnpm install --frozen-lockfile/);
  assert.match(dockerfile, /USER 10001:10001/);
  assert.match(dockerfile, /VOLUME \["\/var\/lib\/piphi"\]/);
  assert.match(dockerfile, /HEALTHCHECK/);
  assert.match(dockerfile, /org\.opencontainers\.image\.revision/);
});
