import assert from "node:assert/strict";
import { mkdtemp, stat } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";

import { acquireStorageLease } from "../src/storage-lock.js";

test("controller storage is private and exclusively leased", async () => {
  const parent = await mkdtemp(join(tmpdir(), "piphi-matter-lock-test-"));
  const storageDir = join(parent, "controller");
  const release = await acquireStorageLease(storageDir);

  const mode = (await stat(storageDir)).mode & 0o777;
  assert.equal(mode, 0o700);
  await assert.rejects(
    acquireStorageLease(storageDir),
    /Refusing to start a duplicate controller/,
  );

  await release();
  const releaseAgain = await acquireStorageLease(storageDir);
  await releaseAgain();
});
