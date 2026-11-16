import assert from "node:assert/strict";
import { mkdtemp } from "node:fs/promises";
import { createServer } from "node:net";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";

import { MatterJsBackend } from "../src/matterjs-backend.js";
import type { MatterSettings } from "../src/settings.js";

test("starts the pinned real Matter Server and reopens its storage", { timeout: 90_000 }, async () => {
  const storageDir = await mkdtemp(join(tmpdir(), "piphi-real-matter-server-"));
  const backendPort = await freePort();
  const settings: MatterSettings = {
    apiHost: "127.0.0.1",
    apiPort: 8710,
    backendHost: "127.0.0.1",
    backendPort,
    backendUrl: `ws://127.0.0.1:${backendPort}/ws`,
    storageDir,
    manageBackend: true,
    enableBle: false,
    dclOffline: true,
    logManagedServer: false,
  };

  const first = new MatterJsBackend(settings);
  let controllerIdentityHash: unknown;
  try {
    await first.start();
    assert.equal(first.connected, true);
    assert.deepEqual(await first.listNodes(), []);
    controllerIdentityHash = (first.diagnostics().server as Record<string, unknown>).controller_identity_hash;
    assert.match(String(controllerIdentityHash), /^[a-f0-9]{16}$/);
    await first.quiesce();
    assert.equal(first.connected, false);
    const duplicate = new MatterJsBackend(settings);
    await assert.rejects(duplicate.start(), /Refusing to start a duplicate controller/);
    await first.resume();
    assert.equal(first.connected, true);
    assert.deepEqual(await first.listNodes(), []);
    assert.equal(
      (first.diagnostics().server as Record<string, unknown>).controller_identity_hash,
      controllerIdentityHash,
    );
  } finally {
    await first.stop();
  }
});

async function freePort(): Promise<number> {
  const server = createServer();
  await new Promise<void>((resolve, reject) => {
    server.once("error", reject);
    server.listen(0, "127.0.0.1", () => resolve());
  });
  const address = server.address();
  if (!address || typeof address === "string") throw new Error("Could not allocate a test port");
  await new Promise<void>((resolve, reject) => server.close((error) => error ? reject(error) : resolve()));
  return address.port;
}
