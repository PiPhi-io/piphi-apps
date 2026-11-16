import assert from "node:assert/strict";
import test from "node:test";

import { checkBluezAdapter, evaluateBluezObjects, type BluezBus } from "../src/ble-preflight.js";

test("BlueZ preflight requires the selected adapter to exist and be powered", () => {
  assert.equal(evaluateBluezObjects({}).reason, "adapter_missing");
  const poweredOff = { "/org/bluez/hci0": { "org.bluez.Adapter1": { Powered: { value: false } } } };
  assert.equal(evaluateBluezObjects(poweredOff).reason, "adapter_powered_off");
  const powered = { "/org/bluez/hci0": { "org.bluez.Adapter1": { Powered: { value: true } } } };
  assert.deepEqual(evaluateBluezObjects(powered), {
    status: "pass", adapter: "hci0", transport: "bluez_dbus",
  });
});

test("BlueZ preflight safely classifies bus and service failures", async () => {
  assert.equal((await checkBluezAdapter("hci0", 10, () => { throw new Error("no bus"); })).reason, "system_bus_unavailable");
  let disconnected = false;
  const unavailable: BluezBus = {
    getProxyObject: async () => { throw new Error("no bluez"); },
    disconnect: () => { disconnected = true; },
  };
  assert.equal((await checkBluezAdapter("hci0", 10, () => unavailable)).reason, "bluez_unavailable");
  assert.equal(disconnected, true);
});

test("BlueZ preflight reads powered adapter state through ObjectManager", async () => {
  let disconnected = false;
  const bus: BluezBus = {
    getProxyObject: async () => ({
      getInterface: () => ({
        GetManagedObjects: async () => ({
          "/org/bluez/hci0": { "org.bluez.Adapter1": { Powered: { value: true } } },
        }),
      }),
    }),
    disconnect: () => { disconnected = true; },
  };
  assert.equal((await checkBluezAdapter("hci0", 10, () => bus)).status, "pass");
  assert.equal(disconnected, true);
});
