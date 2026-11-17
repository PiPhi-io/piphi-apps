import assert from "node:assert/strict";
import test from "node:test";

import {
  assertSetValueSucceeded,
  isSensitiveValue,
  redactControllerPath,
  validateControllerPath,
} from "../src/driver-session.js";

test("setValue reports completion only for confirmed success", () => {
  assert.doesNotThrow(() => assertSetValueSucceeded({ status: 255 }));
  assert.throws(() => assertSetValueSucceeded({ status: 0 }), /set_value_rejected_no_device_support/);
  assert.throws(() => assertSetValueSucceeded({ status: 2 }), /set_value_rejected_fail/);
  assert.throws(() => assertSetValueSucceeded({ status: 3 }), /set_value_rejected_endpoint_not_found/);
  assert.throws(() => assertSetValueSucceeded({ status: 4 }), /set_value_rejected_not_implemented/);
  assert.throws(() => assertSetValueSucceeded({ status: 5 }), /set_value_rejected_invalid_value/);
  assert.throws(() => assertSetValueSucceeded({ status: 1 }), /set_value_result_pending/);
  assert.throws(() => assertSetValueSucceeded({ status: 254 }), /set_value_result_unconfirmed/);
  assert.throws(() => assertSetValueSucceeded(undefined), /set_value_result_invalid/);
});

test("controller path policy accepts stable paths and rejects arbitrary devices", () => {
  assert.doesNotThrow(() => validateControllerPath("/dev/serial/by-id/usb-Z-Wave_Controller-if00"));
  assert.doesNotThrow(() => validateControllerPath("/dev/serial/by-path/pci-0000:00-usb-0:1:1.0"));
  assert.throws(() => validateControllerPath("/dev/ttyACM0"), /stable or explicitly allow-listed/);
  assert.throws(() => validateControllerPath("/dev/serial/by-id/../ttyACM0"), /invalid/);
  assert.throws(() => validateControllerPath("/etc/passwd"), /stable or explicitly allow-listed/);
});

test("diagnostics expose only a short controller path suffix", () => {
  const redacted = redactControllerPath("/dev/serial/by-id/usb-0658_0200-if00");
  assert.equal(redacted, "58_0200-if00");
  assert.doesNotMatch(redacted, /^\/dev\//);
});

test("snapshot and write policy reject sensitive value metadata", () => {
  assert.equal(
    isSensitiveValue(
      { property: "dsk", propertyName: "Device-specific key" },
      { type: "string", readable: true, writeable: true },
    ),
    true,
  );
  assert.equal(
    isSensitiveValue(
      { property: "currentValue", propertyName: "Current value" },
      { type: "boolean", readable: true, writeable: true },
    ),
    false,
  );
});
