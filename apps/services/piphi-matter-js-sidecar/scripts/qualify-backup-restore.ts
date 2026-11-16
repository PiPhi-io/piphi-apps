import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import {
  chmod,
  cp,
  lstat,
  mkdir,
  mkdtemp,
  open,
  readdir,
  readFile,
  rm,
  unlink,
  writeFile,
} from "node:fs/promises";
import { createServer } from "node:net";
import { tmpdir } from "node:os";
import { basename, join, relative } from "node:path";

import { MatterJsBackend } from "../src/matterjs-backend.js";
import type { MatterSettings } from "../src/settings.js";

interface ManifestEntry {
  path: string;
  bytes: number;
  sha256: string;
}

interface BackupManifest {
  format: 1;
  entries: ManifestEntry[];
}

const LEASE_FILE = ".piphi-controller.lock";
const MANIFEST_FILE = "backup-manifest.json";

async function main(): Promise<void> {
  const workspace = await mkdtemp(join(tmpdir(), "piphi-matter-backup-restore-"));
  const sourceDir = join(workspace, "source");
  const backupDir = join(workspace, "backup");
  const restoredDir = join(workspace, "restored");
  const corruptBackupDir = join(workspace, "backup-corrupt");
  const incompleteBackupDir = join(workspace, "backup-incomplete");
  const corruptTargetDir = join(workspace, "corrupt-target");
  const incompleteTargetDir = join(workspace, "incomplete-target");

  let source: MatterJsBackend | undefined;
  let restored: MatterJsBackend | undefined;
  try {
    source = new MatterJsBackend(await settingsFor(sourceDir));
    await source.start();
    const sourceIdentity = identityOf(source);
    assert.match(sourceIdentity, /^[a-f0-9]{16}$/);

    await source.quiesce();
    assert.equal(source.connected, false, "source must be quiesced before it is copied");
    assert.equal(source.diagnostics().storage_locked, true, "quiesce must retain the source lease");
    await createBackup(sourceDir, backupDir);
    await source.stop();
    source = undefined;

    await mkdir(restoredDir, { mode: 0o700 });
    assert.deepEqual(await readdir(restoredDir), [], "restore target must begin empty");
    await restoreBackup(backupDir, restoredDir);

    const restoredSettings = await settingsFor(restoredDir);
    restored = new MatterJsBackend(restoredSettings);
    await restored.start();
    const restoredIdentity = identityOf(restored);
    assert.equal(restoredIdentity, sourceIdentity, "restored controller identity changed");

    const competingClone = new MatterJsBackend(restoredSettings);
    await assert.rejects(
      competingClone.start(),
      /Refusing to start a duplicate controller/,
      "two clones acquired the same restored storage lease",
    );

    await cp(backupDir, corruptBackupDir, { recursive: true });
    const corruptManifest = await readManifest(corruptBackupDir);
    const corruptEntry = corruptManifest.entries.find((entry) => entry.bytes > 0);
    assert.ok(corruptEntry, "backup unexpectedly contained no non-empty files");
    const corruptFile = join(corruptBackupDir, "storage", corruptEntry.path);
    const handle = await open(corruptFile, "r+");
    try {
      await handle.write(Buffer.from([0xff]), 0, 1, 0);
    } finally {
      await handle.close();
    }
    await mkdir(corruptTargetDir, { mode: 0o700 });
    await assert.rejects(restoreBackup(corruptBackupDir, corruptTargetDir), /checksum mismatch/);
    assert.deepEqual(await readdir(corruptTargetDir), [], "corrupt restore modified its target");

    await cp(backupDir, incompleteBackupDir, { recursive: true });
    const incompleteManifest = await readManifest(incompleteBackupDir);
    const missingEntry = incompleteManifest.entries[0];
    assert.ok(missingEntry, "backup unexpectedly contained no files");
    await unlink(join(incompleteBackupDir, "storage", missingEntry.path));
    await mkdir(incompleteTargetDir, { mode: 0o700 });
    await assert.rejects(restoreBackup(incompleteBackupDir, incompleteTargetDir), /missing file/);
    assert.deepEqual(await readdir(incompleteTargetDir), [], "incomplete restore modified its target");

    console.log(`PASS backup copied from quiesced storage (${sourceIdentity})`);
    console.log("PASS restored controller_identity_hash matches source");
    console.log("PASS restored storage permits exactly one lease holder");
    console.log("PASS corrupt and incomplete backups fail closed before target mutation");
  } finally {
    await restored?.stop();
    await source?.stop();
    await rm(workspace, { recursive: true, force: true });
  }
}

async function createBackup(sourceDir: string, backupDir: string): Promise<void> {
  await assertEmptyOrMissing(backupDir);
  const storageDir = join(backupDir, "storage");
  await mkdir(storageDir, { recursive: true, mode: 0o700 });
  await copyDirectoryContents(sourceDir, storageDir, true);
  const entries = await inventory(storageDir);
  assert.ok(entries.length > 0, "quiesced Matter storage was empty");
  const manifest: BackupManifest = { format: 1, entries };
  await writeFile(join(backupDir, MANIFEST_FILE), `${JSON.stringify(manifest, null, 2)}\n`, { mode: 0o600 });
  await verifyBackup(backupDir);
}

async function restoreBackup(backupDir: string, targetDir: string): Promise<void> {
  await verifyBackup(backupDir);
  await assertEmptyDirectory(targetDir);
  await chmod(targetDir, 0o700);
  await copyDirectoryContents(join(backupDir, "storage"), targetDir, false);
}

async function verifyBackup(backupDir: string): Promise<void> {
  const manifest = await readManifest(backupDir);
  const storageDir = join(backupDir, "storage");
  const actualEntries = await inventory(storageDir);
  const actualByPath = new Map(actualEntries.map((entry) => [entry.path, entry]));
  for (const expected of manifest.entries) {
    const actual = actualByPath.get(expected.path);
    if (!actual) throw new Error(`Backup is incomplete: missing file ${expected.path}`);
    if (actual.bytes !== expected.bytes || actual.sha256 !== expected.sha256) {
      throw new Error(`Backup checksum mismatch: ${expected.path}`);
    }
    actualByPath.delete(expected.path);
  }
  if (actualByPath.size > 0) {
    throw new Error(`Backup contains unmanifested file: ${actualByPath.keys().next().value}`);
  }
}

async function readManifest(backupDir: string): Promise<BackupManifest> {
  const parsed = JSON.parse(await readFile(join(backupDir, MANIFEST_FILE), "utf8")) as BackupManifest;
  assert.equal(parsed.format, 1, "unsupported backup manifest format");
  assert.ok(Array.isArray(parsed.entries), "backup manifest entries are missing");
  return parsed;
}

async function inventory(root: string): Promise<ManifestEntry[]> {
  const entries: ManifestEntry[] = [];
  await walk(root, async (path) => {
    const data = await readFile(path);
    entries.push({
      path: relative(root, path),
      bytes: data.byteLength,
      sha256: createHash("sha256").update(data).digest("hex"),
    });
  });
  return entries.sort((left, right) => left.path.localeCompare(right.path));
}

async function walk(directory: string, visit: (path: string) => Promise<void>): Promise<void> {
  const entries = await readdir(directory, { withFileTypes: true });
  entries.sort((left, right) => left.name.localeCompare(right.name));
  for (const entry of entries) {
    const path = join(directory, entry.name);
    if (entry.isDirectory()) await walk(path, visit);
    else if (entry.isFile()) await visit(path);
    else throw new Error(`Refusing to back up non-regular storage entry: ${path}`);
  }
}

async function copyDirectoryContents(source: string, target: string, omitLease: boolean): Promise<void> {
  for (const entry of await readdir(source, { withFileTypes: true })) {
    if (omitLease && entry.name === LEASE_FILE) continue;
    await cp(join(source, entry.name), join(target, entry.name), {
      recursive: true,
      errorOnExist: true,
      force: false,
    });
  }
}

async function assertEmptyOrMissing(path: string): Promise<void> {
  try {
    await assertEmptyDirectory(path);
  } catch (error) {
    if (error && typeof error === "object" && "code" in error && error.code === "ENOENT") return;
    throw error;
  }
}

async function assertEmptyDirectory(path: string): Promise<void> {
  const metadata = await lstat(path);
  if (!metadata.isDirectory()) throw new Error(`Restore target is not a directory: ${path}`);
  if ((await readdir(path)).length !== 0) throw new Error(`Restore target is not empty: ${path}`);
}

function identityOf(backend: MatterJsBackend): string {
  const server = backend.diagnostics().server;
  assert.ok(server && typeof server === "object" && !Array.isArray(server));
  assert.ok("controller_identity_hash" in server);
  const identity = server.controller_identity_hash;
  assert.ok(typeof identity === "string");
  return identity;
}

async function settingsFor(storageDir: string): Promise<MatterSettings> {
  const backendPort = await freePort();
  return {
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
}

async function freePort(): Promise<number> {
  const server = createServer();
  await new Promise<void>((resolve, reject) => {
    server.once("error", reject);
    server.listen(0, "127.0.0.1", resolve);
  });
  const address = server.address();
  assert.ok(address && typeof address !== "string", "could not allocate a test port");
  await new Promise<void>((resolve, reject) => server.close((error) => error ? reject(error) : resolve()));
  return address.port;
}

await main();
