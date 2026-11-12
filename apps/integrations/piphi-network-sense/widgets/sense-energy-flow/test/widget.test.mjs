import test from "node:test";
import assert from "node:assert/strict";
import manifest from "../widget.manifest.json" with { type: "json" };
import { validateWidgetManifest } from "piphi-network-widget-sdk/manifest";
import { readFile } from "node:fs/promises";
import { createSenseStateReducer, describeSenseStreamEvent } from "../src/state.js";
import { execFileSync } from "node:child_process";
import { fileURLToPath } from "node:url";
import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

test("manifest is publishable", () => {
  assert.equal(validateWidgetManifest(manifest).filter((item) => item.severity === "error").length, 0);
});

test("uses the current SDK and one truthful semantic card target", () => {
  assert.equal(manifest.sdk_compatibility.minimum, "0.6.1");
  assert.deepEqual(manifest.interaction_targets.map((target) => target.kind), ["card"]);
  assert.equal(manifest.layout.default_height, 156);
});

test("uses a transparent compact Core-owned surface", async () => {
  const source = await readFile(new URL("../src/widget.js", import.meta.url), "utf8");
  assert.match(source, /background:transparent/);
  assert.doesNotMatch(source, /background:\s*Canvas/);
  assert.match(source, /min-height:44px/);
  assert.match(source, /\[role=status\]\[hidden\]/);
  assert.match(source, /forced-colors:active/);
});

test("reduces current SDK snapshots and points while hiding healthy stream status", () => {
  const reducer = createSenseStateReducer();
  let reduced = reducer.apply({ kind: "snapshot", data: { states: [
    { capability_id: "active_power_w", value: 1250 },
    { capability_id: "active_solar_power_w", value: 800 },
  ] } });
  assert.equal(reduced.values.active_power_w, 1250);
  reduced = reducer.apply({ kind: "point", data: { capabilityId: "active_power_w", value: 1300 } });
  assert.equal(reduced.values.active_power_w, 1300);
  assert.deepEqual(describeSenseStreamEvent({ kind: "status", status: "open" }), { hidden: true, message: "" });
  assert.equal(describeSenseStreamEvent({ kind: "status", status: "reconnecting" }).hidden, false);
  assert.equal(describeSenseStreamEvent({ kind: "error", error: { message: "internal socket failure" } }).message, "Sense data is unavailable.");
});

test("published package contains the manifest runtime and imported reducer", () => {
  const cwd = fileURLToPath(new URL("..", import.meta.url));
  const cache = mkdtempSync(join(tmpdir(), "sense-flow-pack-"));
  try {
    const packed = JSON.parse(execFileSync("npm", ["pack", "--dry-run", "--json"], {
      cwd, encoding:"utf8", env:{ ...process.env, npm_config_cache:cache },
    }));
    const files = new Set(packed[0].files.map((file) => file.path));
    assert.ok(files.has("dist/widget.js"));
    assert.ok(files.has("dist/state.js"));
    assert.ok(files.has("widget.manifest.json"));
  } finally {
    rmSync(cache, { recursive:true, force:true });
  }
});
