import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import manifest from "../widget.manifest.json" with { type: "json" };
import catalog from "../widget-capability-catalog.json" with { type: "json" };
import { validateWidgetManifest } from "piphi-network-widget-sdk/manifest";
import { formatMetric, lifecycleCopy, normalizeLifecycle, projectState } from "../src/view-model.js";

const integrationManifest = JSON.parse(readFileSync(new URL("../../../src/manifest.json", import.meta.url), "utf8"));

test("manifest, catalog, and integration capability contract agree", () => {
  assert.deepEqual(validateWidgetManifest(manifest).filter((item) => item.severity === "error"), []);
  const consumed = catalog.rows.filter((row) => row.status === "implemented").flatMap((row) => row.consumes);
  assert.deepEqual(new Set(manifest.capability_requirements), new Set(consumed));
  for (const capabilityId of manifest.capability_requirements) assert.ok(integrationManifest.capabilities[capabilityId], capabilityId);
  assert.deepEqual(manifest.binding_modes, ["read"]);
  assert.deepEqual(manifest.security.permissions, []);
  assert.deepEqual(manifest.security.allowed_commands, []);
  assert.deepEqual(manifest.security.csp.connect_src, []);
});

test("state projection bounds values and accepts camel-case host data", () => {
  const ids = manifest.capability_requirements;
  const first = ids[0];
  const camel = first.replace(/_([a-z0-9])/g, (_match, value) => value.toUpperCase());
  const projected = projectState({ primaryState: { [camel]: "ready\u0000" } }, ids);
  assert.equal(projected[first], "ready");
  assert.equal(formatMetric(12.345, "%"), "12.3 %");
  assert.equal(formatMetric(true), "Yes");
  assert.equal(formatMetric("DOOR_OPEN"), "Door Open");
  assert.equal(formatMetric(null), "—");
  assert.equal(projectState({ primaryState: { capability_id: "temperature", value: 24.2 } }, ["temperature"]).temperature, 24.2);
  assert.equal(projectState({ capabilityId: "humidity", value: 48 }, ["humidity"]).humidity, 48);
  assert.equal(projectState({ primaryState: 24.2 }, ["temperature"]).temperature, 24.2);
});

test("covers host lifecycle and accessible presentation states", () => {
  for (const state of ["loading", "empty", "live", "stale", "offline", "reconnecting", "denied", "error"]) assert.equal(normalizeLifecycle(state), state);
  assert.equal(normalizeLifecycle("snapshot"), "live");
  assert.equal(normalizeLifecycle("open"), "live");
  assert.equal(normalizeLifecycle("unexpected"), "error");
  assert.equal(lifecycleCopy("open"), "");
  assert.equal(lifecycleCopy("offline"), "Appliance is offline");
  const source = readFileSync(new URL("../src/widget.js", import.meta.url), "utf8");
  for (const token of ["getInjectedPiPhiWidgetHost", "subscribeState", "host.ready", "role=\"status\"", "aria-live=\"polite\"", "prefers-reduced-motion", "localization?.direction", "@media (max-width: 360px)"]) assert.ok(source.includes(token), token);
  assert.ok(source.includes("background: transparent !important"));
  assert.ok(source.includes("background: none !important"));
  assert.ok(!source.includes("background: Canvas"));
  assert.ok(source.includes("@media (max-width: 240px)"));
  assert.ok(source.includes("metricCard.hidden = !showMetric"));
  assert.ok(source.includes("MAX_GLANCE_METRICS = 4"));
  assert.ok(source.includes("grid-auto-rows: 48px"));
  assert.ok(source.includes("border: 1px solid var(--piphi-widget-border"));
  assert.ok(!source.includes("Updated just now"));
  assert.ok(source.includes('main[data-state="live"] .lifecycle { display: none; }'));
  assert.ok(source.includes("ResizeObserver"));
  assert.ok(source.includes("min-height: 0 !important"));
  assert.ok(source.includes("nextHeight === lastReportedHeight"));
  assert.ok(source.includes("host.setHeight(nextHeight)"));
  assert.ok(!source.includes("getAvailableCommands"));
  assert.ok(!source.includes("host.executeCommand"));
  assert.ok(!source.includes('aria-label="Appliance controls"'));
  assert.equal(manifest.layout.default_height, 160);
  assert.ok(manifest.layout.max_height <= 196);
  assert.ok(!source.includes("See climate, air-quality, energy, battery, and filter readings"));
});
