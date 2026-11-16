import assert from "node:assert/strict";
import { mkdtemp } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";

import type { EventMessage } from "@matter-server/ws-client";

import { MatterJsBackend, toPublicMatterEvent } from "../src/matterjs-backend.js";
import type { MatterSettings } from "../src/settings.js";

async function disconnectedBackend(): Promise<MatterJsBackend> {
  const settings: MatterSettings = {
    apiHost: "127.0.0.1",
    apiPort: 8710,
    backendHost: "127.0.0.1",
    backendPort: 5580,
    backendUrl: "ws://127.0.0.1:5580/ws",
    storageDir: await mkdtemp(join(tmpdir(), "piphi-matter-backend-unit-")),
    manageBackend: false,
    enableBle: false,
    dclOffline: false,
    logManagedServer: false,
  };
  return new MatterJsBackend(settings);
}

test("disconnected backend operations consistently fail closed", async () => {
  const backend = await disconnectedBackend();

  assert.deepEqual(backend.diagnostics(), {
    connected: false,
    managed: false,
    child_running: false,
    reconnecting: false,
    restart_attempts: 0,
    storage_locked: false,
    server: null,
  });

  const operations = [
    () => backend.listNodes(),
    () => backend.getNode("1234"),
    () => backend.discoverCommissionables(5),
    () => backend.commissionWithCode("MT:TEST"),
    () => backend.setWifiCredentials("Lab", "secret"),
    () => backend.setThreadDataset("dataset"),
    () => backend.clearWifiCredentials(),
    () => backend.clearThreadDataset(),
    () => backend.removeNode("1234"),
    () => backend.invoke("1234", 1, "turn_on", {}),
    () => backend.invoke("1234", 1, "refresh", {}),
  ];
  for (const operation of operations) {
    await assert.rejects(operation, /Matter\.js backend is not connected/);
  }

  await assert.rejects(
    backend.invoke("1234", 1, "unlock", {}),
    /Unsupported Matter command: unlock/,
  );
  await assert.rejects(
    backend.invoke("1234", 1, "toggle", { unexpected: true }),
    /toggle does not accept arguments/,
  );

  const listener = () => undefined;
  const unsubscribe = backend.onEvent(listener);
  assert.equal(typeof unsubscribe, "function");
  unsubscribe();
  await backend.stop();
});

test("public event normalization covers every allow-listed event shape", () => {
  const attribute = toPublicMatterEvent({
    event: "attribute_updated",
    data: [1234n, "1/6/0", { enabled: true, counters: [1n, 2n] }],
  } as unknown as EventMessage);
  assert.deepEqual(attribute, {
    type: "device.state_changed",
    nodeId: "1234",
    endpointId: 1,
    payload: {
      path: "1/6/0",
      cluster_id: 6,
      attribute_id: 0,
      value: { enabled: true, counters: ["1", "2"] },
    },
  });

  assert.equal(toPublicMatterEvent({
    event: "attribute_updated",
    data: [1234n, "not/a/path", true],
  } as unknown as EventMessage), undefined);

  const nodeEvent = toPublicMatterEvent({
    event: "node_event",
    data: {
      node_id: 1234n,
      endpoint_id: 2,
      cluster_id: 6,
      event_id: 7,
      event_number: 8n,
      priority: 1,
      data: { total: 9n },
    },
  } as unknown as EventMessage);
  assert.deepEqual(nodeEvent, {
    type: "matter.event",
    nodeId: "1234",
    endpointId: 2,
    payload: {
      cluster_id: 6,
      event_id: 7,
      event_number: "8",
      priority: 1,
      data: { total: "9" },
    },
  });
  for (const [endpoint_id, cluster_id] of [[0, 6], [1, 49]]) {
    assert.equal(toPublicMatterEvent({
      event: "node_event",
      data: { node_id: 1n, endpoint_id, cluster_id },
    } as unknown as EventMessage), undefined);
  }

  const node = {
    node_id: 42n,
    available: false,
    date_commissioned: "2026-01-01T00:00:00Z",
    is_bridge: true,
  };
  assert.equal(toPublicMatterEvent({ event: "node_added", data: node } as unknown as EventMessage)?.type, "matter.node_added");
  assert.deepEqual(
    toPublicMatterEvent({ event: "node_removed", data: 42n } as unknown as EventMessage),
    { type: "matter.node_removed", nodeId: "42", payload: {} },
  );
  assert.deepEqual(
    toPublicMatterEvent({ event: "endpoint_added", data: { node_id: 42n, endpoint_id: 3 } } as unknown as EventMessage),
    { type: "matter.endpoint_added", nodeId: "42", endpointId: 3, payload: {} },
  );
  assert.deepEqual(
    toPublicMatterEvent({ event: "endpoint_removed", data: { node_id: 42n, endpoint_id: 3 } } as unknown as EventMessage),
    { type: "matter.endpoint_removed", nodeId: "42", endpointId: 3, payload: {} },
  );
  assert.deepEqual(
    toPublicMatterEvent({ event: "server_shutdown", data: undefined } as unknown as EventMessage),
    { type: "matter.server_shutdown", payload: {} },
  );

  const serverInfo = toPublicMatterEvent({
    event: "server_info_updated",
    data: {
      schema_version: 15,
      min_supported_schema_version: 13,
      sdk_version: "test-sdk",
      wifi_credentials_set: true,
      thread_credentials_set: false,
      bluetooth_enabled: false,
      fabric_id: 1n,
      compressed_fabric_id: 2n,
    },
  } as unknown as EventMessage);
  assert.deepEqual(serverInfo, {
    type: "matter.server_info_updated",
    payload: {
      schema_version: 15,
      min_supported_schema_version: 13,
      sdk_version: "test-sdk",
      wifi_credentials_set: true,
      thread_credentials_set: false,
      bluetooth_enabled: false,
    },
  });
});
