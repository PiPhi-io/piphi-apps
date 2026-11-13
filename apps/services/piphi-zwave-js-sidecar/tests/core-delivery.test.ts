import assert from "node:assert/strict";
import fs from "node:fs";
import test from "node:test";
import { buildCoreEventPayload, createRuntimeStarter } from "piphi-runtime-kit-node";
import { MockCoreServer } from "piphi-runtime-testkit-node";

import { normalizeNodeEvent } from "../src/transport.js";

type Fixture = {
  id: string;
  node_id: number;
  event_type: string;
  args: Record<string, unknown>[];
};

const fixtures = JSON.parse(
  fs.readFileSync("tests/fixtures/realistic-device-events.json", "utf8"),
) as { cases: Fixture[] };

test("delivers representative switch, lock, thermostat, sensor, meter, and battery events to Core", async (t) => {
  const core = await new MockCoreServer().start();
  t.after(async () => core.stop());
  const starter = createRuntimeStarter({
    integrationId: "piphi-zwave-js-sidecar",
    integrationName: "Z-Wave JS sidecar",
    coreBaseUrl: core.baseUrl,
  });
  starter.runtime.auth.update({
    containerId: "00000000-0000-4000-8000-000000000001",
    internalToken: "test-token-not-a-production-secret",
  });

  for (const fixture of fixtures.cases) {
    const event = normalizeNodeEvent(fixture.event_type, { id: fixture.node_id }, fixture.args);
    await starter.eventClient.sendEvent({
      authContext: starter.runtime.auth,
      event: buildCoreEventPayload({
        eventType: "zwave.transport.event",
        integrationId: "piphi-zwave-js-sidecar",
        configId: "controller-test",
        containerId: "00000000-0000-4000-8000-000000000001",
        deviceId: "zwave-js-controller",
        source: "piphi-zwave-js-sidecar",
        ts: event.occurred_at,
        payload: { event },
      }),
    });
  }

  assert.equal(core.eventRequests.length, fixtures.cases.length);
  const delivered = core.eventRequests.map((request) => request.body?.data?.event as Record<string, unknown>);
  assert.deepEqual(delivered.map((event) => event.command_class), [37, 98, 67, 49, 50, 128]);
  for (const request of core.eventRequests) {
    assert.equal(request.body?.type, "zwave.transport.event");
    assert.equal(request.body?.integration_id, "piphi-zwave-js-sidecar");
    assert.doesNotMatch(request.rawBody, /00112233445566778899aabbccddeeff/);
  }
});
