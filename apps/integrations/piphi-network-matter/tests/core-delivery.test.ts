import assert from "node:assert/strict";
import { test } from "node:test";
import { MockCoreServer } from "piphi-runtime-testkit-node";
import { CoreClient } from "../src/core-client.js";

test("delivers normalized state through the Runtime TestKit Core contract", async () => {
  const core = await new MockCoreServer().start();
  try {
    const client = new CoreClient({
      endpoint: `${core.baseUrl}/api/v2/integrations/telemetry`,
      eventEndpoint: `${core.baseUrl}/api/v2/events/ingest`,
      containerId: "matter-parent-container",
      token: "core-internal-token",
      configId: "matter-config",
    });
    const delivery = await client.telemetry({
      id: "matter:fabric-test:node-17:1",
      device_id: "matter:fabric-test:node-17",
      name: "Desk plug",
      device_class: "switch",
      capabilities: ["connected", "switch_on"],
      available_commands: ["turn_on", "turn_off", "toggle"],
      state: { connected: true, switch_on: true },
      metadata: { controller_identity_hash: "fabric-test", node_id: "node-17", endpoint_id: 1, source: "matter_sidecar" },
    });
    assert.equal(delivery, "delivered");
    assert.equal(core.telemetryRequests.length, 1);
    const body = core.telemetryRequests[0]?.body as unknown as Record<string, unknown>;
    assert.deepEqual(body.device_id, "matter:fabric-test:node-17");
    assert.deepEqual(body.metrics, { connected: true, switch_on: true });
    const eventDelivery = await client.stateChanged({
      id: "matter:fabric-test:node-17:1",
      device_id: "matter:fabric-test:node-17",
      name: "Desk plug",
      device_class: "switch",
      capabilities: ["connected", "switch_on"],
      available_commands: ["turn_on", "turn_off", "toggle"],
      state: { connected: true, switch_on: true },
      metadata: { controller_identity_hash: "fabric-test", node_id: "node-17", endpoint_id: 1, source: "matter_sidecar" },
    }, { connected: true, switch_on: false });
    assert.equal(eventDelivery, "delivered");
    assert.equal(core.eventRequests.length, 1);
    assert.equal(core.eventRequests[0]?.body?.type, "device.state_changed");
  } finally {
    await core.stop();
  }
});
