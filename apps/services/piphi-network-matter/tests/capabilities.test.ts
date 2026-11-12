import assert from "node:assert/strict";
import test from "node:test";

import { normalizeNode } from "../src/capabilities.js";
import { sampleNode } from "./fake-backend.js";

test("normalizes negotiated Matter clusters without a global capability superset", () => {
  const [endpoint] = normalizeNode(sampleNode());
  assert.ok(endpoint);
  assert.deepEqual(endpoint.deviceTypes, ["dimmable_light", "temperature_sensor"]);
  assert.deepEqual(endpoint.capabilities, [
    "battery_percent", "brightness_percent", "connected", "humidity_percent",
    "occupancy_detected", "switch_on", "temperature_c",
  ]);
  assert.deepEqual(endpoint.commandBindings, ["refresh", "toggle", "turn_off", "turn_on"]);
  assert.deepEqual(endpoint.state, {
    connected: true, switch_on: true, brightness_percent: 50, temperature_c: 22.45,
    humidity_percent: 41.5, occupancy_detected: true, battery_percent: 85,
  });
});

test("does not advertise switch commands when the On/Off cluster is absent", () => {
  const node = sampleNode();
  node.attributes = {
    "0/40/3": "Temperature Sensor",
    "1/29/0": [{ deviceType: 0x0302 }],
    "1/29/1": [1026],
    "1/1026/0": 1999,
  };
  const [endpoint] = normalizeNode(node);
  assert.deepEqual(endpoint?.capabilities, ["connected", "temperature_c"]);
  assert.deepEqual(endpoint?.commandBindings, ["refresh"]);
});
