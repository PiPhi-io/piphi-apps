import assert from "node:assert/strict";
import { mkdtemp } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";

import { MatterJsBackend } from "../src/matterjs-backend.js";
import type { MatterSettings } from "../src/settings.js";
import type { MatterEvent } from "../src/types.js";

interface RecordedCommand {
  message_id: string;
  command: string;
  args: Record<string, unknown>;
}

const node = {
  node_id: 1234,
  date_commissioned: "2026-11-15T12:00:00Z",
  last_interview: "2026-11-15T12:01:00Z",
  interview_version: 1,
  available: true,
  is_bridge: false,
  attributes: { "1/6/0": false, nested: { count: 7 } },
  attribute_subscriptions: [],
  matter_version: "1.4",
};

class ControlledMatterServer {
  readonly commands: RecordedCommand[] = [];
  readonly sockets = new Set<ControlledWebSocket>();
  connectionCount = 0;

  attach(socket: ControlledWebSocket): void {
    this.sockets.add(socket);
    this.connectionCount += 1;
    queueMicrotask(() => socket.open({
      sdk_version: "1.6.0-test",
      schema_version: 15,
      min_supported_schema_version: 13,
      wifi_credentials_set: false,
      thread_credentials_set: false,
      bluetooth_enabled: false,
      fabric_id: 11,
      compressed_fabric_id: 22,
    }));
  }

  receive(socket: ControlledWebSocket, data: string): void {
    const command = JSON.parse(data) as RecordedCommand;
    this.commands.push(command);
    let result: unknown;
    if (command.command === "start_listening") result = [];
    else if (command.command === "get_nodes") result = [node];
    else if (command.command === "get_node" || command.command === "commission_with_code") result = node;
    else if (command.command === "discover_commissionable_nodes") {
      result = [
        {
          instance_name: "test-light",
          vendor_id: 0xfff1,
          product_id: 0x8000,
          device_type: 0x0100,
          long_discriminator: 3840,
          commissioning_mode: 1,
          addresses: ["fe80::1"],
        },
        {},
      ];
    } else if (command.command === "get_all_credentials") {
      result = { wifi: [{ id: "default", ssid: "Home" }, { id: "piphi-provision-orphan", ssid: "Lab" }], thread: [] };
    } else if (command.command === "device_command") result = { status: "accepted" };
    socket.message({ message_id: command.message_id, result: result ?? null });
  }

  emit(event: Record<string, unknown>): void {
    for (const socket of this.sockets) socket.message(event);
  }

  dropConnections(): void {
    for (const socket of [...this.sockets]) socket.drop();
  }

  detach(socket: ControlledWebSocket): void {
    this.sockets.delete(socket);
  }
}

let controlledServer: ControlledMatterServer;

class ControlledWebSocket {
  readyState = 0;
  onopen: ((event: unknown) => void) | null = null;
  onclose: ((event: unknown) => void) | null = null;
  onerror: ((event: unknown) => void) | null = null;
  onmessage: ((event: { data: unknown }) => void) | null = null;

  constructor(_url: string) {
    controlledServer.attach(this);
  }

  open(serverInfo: Record<string, unknown>): void {
    if (this.readyState !== 0) return;
    this.readyState = 1;
    this.onopen?.({});
    this.message(serverInfo);
  }

  send(data: string): void {
    assert.equal(this.readyState, 1, "commands require an open controlled connection");
    controlledServer.receive(this, data);
  }

  message(value: Record<string, unknown>): void {
    queueMicrotask(() => this.onmessage?.({ data: JSON.stringify(value) }));
  }

  close(): void {
    this.drop();
  }

  drop(): void {
    if (this.readyState === 3) return;
    this.readyState = 3;
    controlledServer.detach(this);
    queueMicrotask(() => this.onclose?.({}));
  }
}

test("routes lifecycle, credentials, discovery, and commands through a reconnecting client", async () => {
  const originalWebSocket = globalThis.WebSocket;
  controlledServer = new ControlledMatterServer();
  globalThis.WebSocket = ControlledWebSocket as unknown as typeof WebSocket;
  const storageDir = await mkdtemp(join(tmpdir(), "piphi-controlled-matter-client-"));
  const settings: MatterSettings = {
    apiHost: "127.0.0.1",
    apiPort: 8710,
    backendHost: "127.0.0.1",
    backendPort: 5580,
    backendUrl: "ws://controlled.test/ws",
    storageDir,
    manageBackend: false,
    enableBle: false,
    dclOffline: true,
    logManagedServer: false,
  };
  const backend = new MatterJsBackend(settings);
  const events: MatterEvent[] = [];
  const unsubscribe = backend.onEvent((event) => events.push(event));

  try {
    await backend.start();
    await backend.start();
    assert.equal(backend.connected, true);
    assert.equal(controlledServer.connectionCount, 1, "start is idempotent while connected");
    assert.deepEqual(backend.diagnostics().server, {
      sdk_version: "1.6.0-test",
      schema_version: 15,
      min_supported_schema_version: 13,
      wifi_credentials_set: false,
      thread_credentials_set: false,
      bluetooth_enabled: false,
      controller_identity_hash: "a54809cceb32e1e0",
    });

    assert.deepEqual(await backend.listNodes(), [{
      nodeId: "1234",
      available: true,
      dateCommissioned: "2026-11-15T12:00:00Z",
      matterVersion: "1.4",
      attributes: { "1/6/0": false, nested: { count: 7 } },
    }]);
    assert.equal((await backend.getNode("1234")).nodeId, "1234");
    assert.equal((await backend.commissionWithCode("MT:CONTROLLED", true)).nodeId, "1234");
    assert.deepEqual(await backend.discoverCommissionables(3), [
      {
        instanceName: "test-light",
        vendorId: 0xfff1,
        productId: 0x8000,
        deviceType: 0x0100,
        longDiscriminator: 3840,
        commissioningMode: 1,
        addresses: ["fe80::1"],
      },
      { addresses: [] },
    ]);

    await backend.setWifiCredentials("Lab WiFi", "wifi-secret");
    await backend.setWifiCredentials("Provisioning WiFi", "temporary-secret", "piphi-test");
    await backend.commissionWithCode("MT:BLE-CONTROLLED", false, {
      wifiCredentialsId: "piphi-test", discoveryTimeoutSeconds: 180, timeoutMs: 300_000,
    });
    await backend.setThreadDataset("thread-dataset");
    await backend.clearWifiCredentials();
    await backend.clearWifiCredentials("piphi-test");
    assert.equal(await backend.clearTemporaryWifiCredentials("piphi-provision-"), 1);
    await backend.clearThreadDataset();
    await backend.removeNode("1234");
    assert.deepEqual(await backend.invoke("1234", 1, "turn_on", {}), { status: "accepted" });
    assert.deepEqual(await backend.invoke("1234", 1, "turn_off", {}), { status: "accepted" });
    assert.deepEqual(await backend.invoke("1234", 1, "toggle", {}), { status: "accepted" });
    assert.deepEqual(await backend.invoke("1234", 1, "refresh", {}), { refreshed: true });

    const credentialCommands = controlledServer.commands.filter(({ command }) => command.includes("credentials") || command.includes("dataset"));
    assert.deepEqual(credentialCommands.map(({ command, args }) => ({ command, args })), [
      { command: "set_wifi_credentials", args: { ssid: "Lab WiFi", credentials: "wifi-secret" } },
      { command: "set_wifi_credentials", args: { ssid: "Provisioning WiFi", credentials: "temporary-secret", id: "piphi-test" } },
      { command: "set_thread_dataset", args: { dataset: "thread-dataset" } },
      { command: "remove_wifi_credentials", args: {} },
      { command: "remove_wifi_credentials", args: { id: "piphi-test" } },
      { command: "get_all_credentials", args: {} },
      { command: "remove_wifi_credentials", args: { id: "piphi-provision-orphan" } },
      { command: "remove_thread_dataset", args: {} },
    ]);
    assert.deepEqual(
      controlledServer.commands.find(({ command, args }) => command === "commission_with_code" && args.code === "MT:BLE-CONTROLLED")?.args,
      {
        code: "MT:BLE-CONTROLLED",
        network_only: false,
        wifi_credentials_id: "piphi-test",
        discovery_timeout_s: 180,
      },
    );
    assert.deepEqual(
      controlledServer.commands.filter(({ command }) => command === "device_command").map(({ args }) => args),
      ["on", "off", "toggle"].map((command_name) => ({
        node_id: 1234,
        endpoint_id: 1,
        cluster_id: 6,
        command_name,
        payload: {},
        response_type: null,
      })),
    );

    controlledServer.emit({ event: "attribute_updated", data: [1234, "1/6/0", true] });
    await waitFor(() => events.some(({ type }) => type === "device.state_changed"));
    assert.equal(events.find(({ type }) => type === "device.state_changed")?.node_id, "1234");

    controlledServer.dropConnections();
    await waitFor(() => events.some(({ type }) => type === "backend.connection_lost"));
    assert.equal(backend.connected, false);
    await waitFor(() => events.some(({ type }) => type === "backend.reconnected"), 3_000);
    assert.equal(backend.connected, true);
    assert.equal(controlledServer.connectionCount, 2);
    assert.equal(backend.diagnostics().restart_attempts, 0);
  } finally {
    unsubscribe();
    await backend.stop();
    globalThis.WebSocket = originalWebSocket;
  }
});

async function waitFor(predicate: () => boolean, timeout = 1_000): Promise<void> {
  const deadline = Date.now() + timeout;
  while (!predicate()) {
    if (Date.now() >= deadline) throw new Error("Timed out waiting for controlled Matter client state");
    await new Promise((resolve) => setTimeout(resolve, 10));
  }
}
