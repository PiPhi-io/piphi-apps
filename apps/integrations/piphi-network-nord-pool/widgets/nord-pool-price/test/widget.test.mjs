import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import manifest from "../widget.manifest.json" with { type: "json" };
import catalog from "../widget-capability-catalog.json" with { type: "json" };
import { validateWidgetManifest } from "piphi-network-widget-sdk/manifest";
import { formatPrice, normalizeLifecycle, projectState } from "../src/model.js";

const integrationManifest = JSON.parse(readFileSync(new URL("../../../manifest.json", import.meta.url), "utf8"));

test("widget and integration contracts agree", () => {
  assert.deepEqual(validateWidgetManifest(manifest).filter((item) => item.severity === "error"), []);
  const consumed = catalog.rows.filter((row) => row.status === "implemented").flatMap((row) => row.consumes);
  assert.deepEqual(new Set(manifest.capability_requirements), new Set(consumed));
  for (const id of manifest.capability_requirements) assert.ok(integrationManifest.capabilities[id], id);
  assert.deepEqual(manifest.binding_modes, ["read"]);
  assert.deepEqual(manifest.security.permissions, []);
  assert.deepEqual(manifest.security.csp.connect_src, []);
});

test("price projection handles missing, malformed, and untrusted values", () => {
  const state = projectState({ primaryState: {
    connected: true, marketArea: "SE3\u0000", currentPricePerKwh: 0.123,
    nextPricePerKwh: Number.NaN, priceUnit: "EUR/kWh",
  } });
  assert.equal(state.market_area, "SE3");
  assert.equal(state.current_price_per_kwh, 0.123);
  assert.equal(state.next_price_per_kwh, null);
  assert.equal(formatPrice(null), "—");
  assert.equal(formatPrice(0.123, "en"), "0.123");
  const serialized = projectState({ states: [
    { capability_id: "connected", value: true },
    { capability_id: "current_price_per_kwh", value: 0.125 },
    { capability_id: "price_unit", value: "EUR/kWh" },
  ] });
  assert.equal(serialized.connected, true);
  assert.equal(serialized.current_price_per_kwh, 0.125);
  assert.equal(serialized.price_unit, "EUR/kWh");
});

test("lifecycle and host handshake cover accessibility states", () => {
  for (const state of manifest.conformance.states) assert.equal(normalizeLifecycle(state), state);
  assert.equal(normalizeLifecycle("snapshot"), "live");
  assert.equal(normalizeLifecycle("open"), "live");
  assert.equal(normalizeLifecycle("connecting"), "reconnecting");
  assert.equal(normalizeLifecycle("closed"), "reconnecting");
  const source = readFileSync(new URL("../src/widget.js", import.meta.url), "utf8");
  for (const token of ["getInjectedPiPhiWidgetHost", "subscribeState", "host.ready", "role=\"status\"", "aria-live=\"polite\"", "prefers-reduced-motion", "localization?.direction", "@media (max-width: 360px)"]) {
    assert.ok(source.includes(token), token);
  }
  assert.deepEqual(manifest.layout, { min_height: 120, default_height: 140, max_height: 220 });
  assert.match(source, /main \{ min-height: 128px; padding: 14px;/);
  assert.match(source, /host\.setHeight\(Math\.min\(220, Math\.max\(130, root\.scrollHeight \+ 2\)\)\)/);
  assert.match(source, /host\.ready\(\{ height: 140 \}\)/);
});
