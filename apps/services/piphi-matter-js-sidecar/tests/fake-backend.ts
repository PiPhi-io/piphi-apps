import { randomUUID } from "node:crypto";

import type {
  JsonObject,
  MatterBackend,
  MatterCommissionable,
  MatterEvent,
  MatterNodeSnapshot,
} from "../src/types.js";

export class FakeMatterBackend implements MatterBackend {
  connected = false;
  nodes: MatterNodeSnapshot[];
  invocations: Array<{ nodeId: string; endpointId: number; command: string; args: JsonObject }> = [];
  wifiCredentials: { ssid: string; credentials: string } | undefined;
  bluetoothEnabled = false;
  readonly wifiCredentialEntries = new Map<string, { ssid: string; credentials: string }>();
  readonly provisioningCalls: Array<{ operation: string; id?: string; networkOnly?: boolean }> = [];
  threadDataset: string | undefined;
  threadDatasetClearCount = 0;
  readonly #listeners = new Set<(event: MatterEvent) => void>();

  constructor(nodes: MatterNodeSnapshot[] = [sampleNode()]) {
    this.nodes = nodes;
  }

  diagnostics(): JsonObject {
    return {
      connected: this.connected,
      fake: true,
      server: {
        controller_identity_hash: "fabric-test",
        sdk_version: "matter-server/1.6.0",
        schema_version: 15,
        bluetooth_enabled: this.bluetoothEnabled,
      },
    };
  }

  async start(): Promise<void> { this.connected = true; }
  async quiesce(): Promise<void> { this.connected = false; }
  async resume(): Promise<void> { this.connected = true; }
  async stop(): Promise<void> { this.connected = false; }
  async listNodes(): Promise<MatterNodeSnapshot[]> { return structuredClone(this.nodes); }
  async getNode(nodeId: string): Promise<MatterNodeSnapshot> {
    const node = this.nodes.find((item) => item.nodeId === nodeId);
    if (!node) throw new Error(`Node ${nodeId} not found`);
    return structuredClone(node);
  }
  async discoverCommissionables(_timeoutSeconds: number): Promise<MatterCommissionable[]> {
    return [{ instanceName: "test-light", vendorId: 4660, productId: 1, addresses: ["fd00::1"] }];
  }
  async commissionWithCode(_setupCode: string, networkOnly = false, options: { wifiCredentialsId?: string } = {}): Promise<MatterNodeSnapshot> {
    this.provisioningCalls.push({ operation: "commission", networkOnly, ...(options.wifiCredentialsId ? { id: options.wifiCredentialsId } : {}) });
    const node = sampleNode("9001");
    this.nodes.push(node);
    return structuredClone(node);
  }
  async setWifiCredentials(ssid: string, credentials: string, id?: string): Promise<void> {
    this.provisioningCalls.push({ operation: "set", ...(id ? { id } : {}) });
    if (id) this.wifiCredentialEntries.set(id, { ssid, credentials });
    else this.wifiCredentials = { ssid, credentials };
  }
  async setThreadDataset(dataset: string): Promise<void> { this.threadDataset = dataset; }
  async clearWifiCredentials(id?: string): Promise<void> {
    this.provisioningCalls.push({ operation: "clear", ...(id ? { id } : {}) });
    if (id) this.wifiCredentialEntries.delete(id);
    else this.wifiCredentials = undefined;
  }
  async clearTemporaryWifiCredentials(prefix: string): Promise<number> {
    const ids = [...this.wifiCredentialEntries.keys()].filter((id) => id.startsWith(prefix));
    for (const id of ids) this.wifiCredentialEntries.delete(id);
    return ids.length;
  }
  async clearThreadDataset(): Promise<void> {
    this.threadDatasetClearCount += 1;
    this.threadDataset = undefined;
  }
  async removeNode(nodeId: string): Promise<void> { this.nodes = this.nodes.filter((item) => item.nodeId !== nodeId); }
  async invoke(nodeId: string, endpointId: number, command: string, args: JsonObject): Promise<unknown> {
    this.invocations.push({ nodeId, endpointId, command, args });
    return { accepted: true };
  }
  onEvent(listener: (event: MatterEvent) => void): () => void {
    this.#listeners.add(listener);
    return () => this.#listeners.delete(listener);
  }
  emit(type = "matter.event"): void {
    const event: MatterEvent = { id: randomUUID(), type, timestamp: new Date().toISOString(), node_id: "1234", endpoint_id: 1, payload: {} };
    for (const listener of this.#listeners) listener(event);
  }
}

export function sampleNode(nodeId = "1234"): MatterNodeSnapshot {
  return {
    nodeId,
    available: true,
    matterVersion: "1.4.0",
    attributes: {
      "0/40/1": "PiPhi Labs",
      "0/40/2": 4660,
      "0/40/3": "Climate Light",
      "0/40/4": 1,
      "0/40/5": "Office Matter Device",
      "0/40/7": 1,
      "0/40/8": "1.0",
      "0/40/9": 100,
      "0/40/10": "1.0.0",
      "1/29/0": [{ deviceType: 0x0101, revision: 3 }, { deviceType: 0x0302, revision: 2 }],
      "1/29/1": [6, 8, 47, 1026, 1029, 1030],
      "1/6/0": true,
      "1/8/0": 127,
      "1/47/12": 170,
      "1/1026/0": 2245,
      "1/1029/0": 4150,
      "1/1030/0": 1,
    },
  };
}
