import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createHash } from "node:crypto";
import test from "node:test";
import manifest from "../widget.manifest.json" with { type: "json" };
import catalog from "../widget-capability-catalog.json" with { type: "json" };
import { validateWidgetManifest } from "piphi-network-widget-sdk/manifest";
import { formatStatus, normalizeLifecycle, projectState } from "../src/model.js";

const integrationManifest = JSON.parse(readFileSync(new URL("../../../manifest.json", import.meta.url), "utf8"));

test("widget and integration capabilities match", () => {
  assert.deepEqual(validateWidgetManifest(manifest).filter((item) => item.severity === "error"), []);
  const consumed = catalog.rows.filter((row) => row.status === "implemented").flatMap((row) => row.consumes);
  assert.deepEqual(new Set(manifest.capability_requirements), new Set(consumed));
  for (const id of manifest.capability_requirements) assert.ok(integrationManifest.capabilities[id], id);
  assert.deepEqual(manifest.binding_modes, ["read"]);
  assert.deepEqual(manifest.security.permissions, []);
  const bundle = readFileSync(new URL("../dist/widget.js", import.meta.url));
  assert.equal(manifest.integrity, `sha256-${createHash("sha256").update(bundle).digest("base64")}`);
  assert.ok(!bundle.toString().includes('from "./model.js"'));
  assert.ok(!bundle.toString().includes('from "piphi-network-widget-sdk"'));
});

test("printer projection rejects invalid or unsafe values", () => {
  const state = projectState({ primaryState: {
    connected: true, print_status: "RUNNING", print_progress_percent: 62,
    remaining_time_minutes: -1, current_layer: 148, total_layers: 240,
    nozzle_temperature_c: Infinity, bed_temperature_c: 60,
  } });
  assert.equal(state.print_progress_percent, 62);
  assert.equal(state.remaining_time_minutes, null);
  assert.equal(state.nozzle_temperature_c, null);
  assert.equal(state.bed_temperature_c, 60);
  assert.equal(formatStatus("RUNNING"), "Running");
  assert.equal(projectState({ state: { print_status: "<script>" } }).print_status, "");
  const serialized = projectState({ states: [
    { capability_id: "connected", value: true },
    { capability_id: "print_status", value: "RUNNING" },
    { capability_id: "print_progress_percent", value: 62 },
  ] });
  assert.equal(serialized.connected, true);
  assert.equal(serialized.print_status, "RUNNING");
  assert.equal(serialized.print_progress_percent, 62);
  assert.equal(projectState({ states: [{ capability_id: "print_status", value: "simulated" }] }).print_status, "simulated");
});

test("widget includes accessibility and lifecycle handling", () => {
  for (const state of manifest.conformance.states) assert.equal(normalizeLifecycle(state), state);
  assert.equal(normalizeLifecycle("open"), "live");
  assert.equal(normalizeLifecycle("connecting"), "reconnecting");
  assert.equal(normalizeLifecycle("closed"), "reconnecting");
  const source = readFileSync(new URL("../src/widget.js", import.meta.url), "utf8");
  for (const token of ["getInjectedPiPhiWidgetHost", "subscribeState", "host.ready", "<progress", "role=\"status\"", "aria-live=\"polite\"", "prefers-reduced-motion", "localization?.direction"]) {
    assert.ok(source.includes(token), token);
  }
});
