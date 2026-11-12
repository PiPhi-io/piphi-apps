import assert from "node:assert/strict";
import test from "node:test";

import { commandForPower, formatReading, normalizeBoolean, statesFromEvent } from "../assets/kasa-widget.mjs";
import { formatMetric, modeForPackageId } from "../assets/kasa-metrics-widget.mjs";

test("control widget normalizes state and chooses safe explicit commands", () => {
  assert.equal(normalizeBoolean("on"), true);
  assert.equal(commandForPower(true), "turn_off");
  assert.equal(commandForPower(false), "turn_on");
  assert.equal(formatReading(12.25, "W"), "12.25 W");
  assert.equal(statesFromEvent({ kind: "point", data: { capabilityId: "switch", value: true } })[0].capability_id, "switch");
});

test("metric widget selects the package-specific view and formats readings", () => {
  assert.equal(modeForPackageId("io.piphi/kasa-smart-home/environment-monitor"), "environment");
  assert.equal(modeForPackageId("io.piphi/kasa-smart-home/energy-monitor"), "energy");
  assert.equal(formatMetric({ value: 22.456 }, "°C"), "22.46 °C");
  assert.equal(formatMetric(undefined, "W"), "—");
});
