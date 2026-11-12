import test from "node:test";
import assert from "node:assert/strict";
import manifest from "../widget.manifest.json" with { type: "json" };
import { validateWidgetManifest } from "piphi-network-widget-sdk/manifest";
import { readFile } from "node:fs/promises";
import { execFileSync } from "node:child_process";
import { fileURLToPath } from "node:url";
import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { createSenseStateReducer, describeSenseStreamEvent } from "../src/state.js";
import { applyApplianceView, createApplianceView } from "../src/view.js";

test("manifest is publishable", () => {
  assert.equal(validateWidgetManifest(manifest).filter((item) => item.severity === "error").length, 0);
});

test("uses the current SDK and one truthful semantic card target", () => {
  assert.equal(manifest.sdk_compatibility.minimum, "0.6.1");
  assert.deepEqual(manifest.interaction_targets.map((target) => target.kind), ["card"]);
  assert.equal(manifest.layout.default_height, 112);
});

test("uses a compact Core-owned appliance surface", async () => {
  const source = await readFile(new URL("../src/widget.js", import.meta.url), "utf8");
  assert.match(source, /background:transparent/);
  assert.doesNotMatch(source, /background:\s*Canvas/);
  assert.match(source, /\[role=status\]\[hidden\]/);
  assert.match(source, /forced-colors:active/);
  assert.doesNotMatch(source, /Detected devices/);
  assert.doesNotMatch(source, /more devices/);
  assert.ok(source.includes('class="label">Now</span>'));
  assert.equal(source.includes('class="label">Using now</span>'), false);
  assert.match(source, /\.state \{[^}]*font-size:12px/);
  assert.match(source, /\.label \{[^}]*font-size:12px/);
  assert.match(source, /\[role=status\] \{[^}]*font-size:12px/);
  assert.doesNotMatch(source, /font-size:\.75rem/);
});

test("reduces device snapshots and points with source metadata", () => {
  const reducer = createSenseStateReducer();
  let reduced = reducer.apply({ kind: "snapshot", data: {
    configId: "dryer", primarySourceLabel: "Telemetry", binding: { deviceLabel: "Dryer" }, states: [
      { capability_id: "device_power_w", value: 450 },
      { capability_id: "device_on", value: true },
      { capability_id: "always_on_power_w", value: 80 },
    ],
  } });
  assert.equal(reduced.meta.sourceLabel, "Dryer");
  assert.equal(reduced.meta.provenanceLabel, "Telemetry");
  assert.equal(reduced.values.device_power_w, 450);
  reduced = reducer.apply({ kind: "point", data: { capabilityId: "device_power_w", value: 500 } });
  assert.equal(reduced.values.device_power_w, 500);
  assert.equal(describeSenseStreamEvent({ kind: "status", status: "open" }).hidden, true);
  assert.equal(describeSenseStreamEvent({ kind: "status", status: "closed" }).hidden, false);
});

test("renders one bound appliance with truthful power, state, and energy", () => {
  const view = createApplianceView(
    { device_power_w: 800, device_on: true, device_daily_energy_kwh: 1.2 },
    { sourceLabel: "Oven" },
  );
  const nodes = Object.fromEntries(["title", "state", "power", "energy"].map((key) => [key, { textContent: "" }]));
  applyApplianceView(nodes, view);
  assert.deepEqual(Object.fromEntries(Object.entries(nodes).map(([key, node]) => [key, node.textContent])), {
    title: "Oven", state: "On", power: "800 W", energy: "1.2 kWh",
  });
});

test("renders missing readings without inventing zero values", () => {
  assert.deepEqual(createApplianceView({}, {}), {
    title: "Sense appliance", state: "Waiting", power: "—", energy: "—",
  });
  assert.equal(createApplianceView({ device_power_w: 0, device_on: false }).state, "Off");
});

test("manifest describes a single bound appliance, not unsupported multi-device data", () => {
  assert.equal(manifest.name, "Sense appliance energy");
  assert.deepEqual(manifest.capability_requirements, ["device_power_w", "device_on", "device_daily_energy_kwh"]);
  assert.deepEqual(manifest.settings.map((setting) => setting.id), ["title"]);
});

test("published package contains the manifest runtime and every imported module", () => {
  const cwd = fileURLToPath(new URL("..", import.meta.url));
  const cache = mkdtempSync(join(tmpdir(), "sense-widget-pack-"));
  try {
    const packed = JSON.parse(execFileSync("npm", ["pack", "--dry-run", "--json"], {
      cwd, encoding: "utf8", env: { ...process.env, npm_config_cache:cache },
    }));
    const files = new Set(packed[0].files.map((file) => file.path));
    assert.ok(files.has("dist/widget.js"));
    assert.ok(files.has("dist/state.js"));
    assert.ok(files.has("dist/view.js"));
    assert.ok(files.has("widget.manifest.json"));
    assert.equal(files.has("dist/model.js"), false);
  } finally {
    rmSync(cache, { recursive:true, force:true });
  }
});
