import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { readFile } from "node:fs/promises";
import { resolve } from "node:path";
import entry from "../registry/widget-entry.json" with { type: "json" };

const archive = resolve("widgets/webrtc-camera", entry.artifact.release_asset);
const digest = `sha256:${createHash("sha256").update(await readFile(archive)).digest("hex")}`;
assert.equal(digest, entry.artifact.integrity, "Packed archive does not match registry integrity");
console.log(`${entry.artifact.release_asset} matches ${digest}.`);
