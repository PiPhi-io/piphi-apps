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
  threadDataset: string | undefined;
  readonly #listeners = new Set<(event: MatterEvent) => void>();

  constructor(nodes: MatterNodeSnapshot[] = [sampleNode()]) {
    this.nodes = nodes;
  }

  async start(): Promise<void> { this.connected = true; }
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
  async commissionWithCode(_setupCode: string): Promise<MatterNodeSnapshot> {
    const node = sampleNode("9001");
    this.nodes.push(node);
    return structuredClone(node);
  }
  async setWifiCredentials(ssid: string, credentials: string): Promise<void> { this.wifiCredentials = { ssid, credentials }; }
  async setThreadDataset(dataset: string): Promise<void> { this.threadDataset = dataset; }
  async clearWifiCredentials(): Promise<void> { this.wifiCredentials = undefined; }
  async clearThreadDataset(): Promise<void> { this.threadDataset = undefined; }
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
