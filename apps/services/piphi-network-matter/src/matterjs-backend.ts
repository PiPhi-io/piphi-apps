import { MatterClient, type EventMessage, type MatterNode } from "@matter-server/ws-client";
import { randomUUID } from "node:crypto";
import { spawn, type ChildProcess } from "node:child_process";
import { mkdir } from "node:fs/promises";
import { setTimeout as delay } from "node:timers/promises";
import { fileURLToPath } from "node:url";

import type { MatterSettings } from "./settings.js";
import type {
  JsonObject,
  MatterBackend,
  MatterCommissionable,
  MatterEvent,
  MatterNodeSnapshot,
} from "./types.js";

export class MatterJsBackend implements MatterBackend {
  #child: ChildProcess | undefined;
  #client: MatterClient | undefined;
  #connected = false;
  #stopping = false;
  #reconnecting: Promise<void> | undefined;
  #restartAttempts = 0;
  #listeners = new Set<(event: MatterEvent) => void>();

  constructor(private readonly settings: MatterSettings) {}

  get connected(): boolean {
    return this.#connected;
  }

  async start(): Promise<void> {
    if (this.#connected) return;
    this.#stopping = false;
    if (process.env.MATTER_CLIENT_DEBUG !== "true") console.debug = () => undefined;
    await mkdir(this.settings.storageDir, { recursive: true, mode: 0o700 });
    if (this.settings.manageBackend) this.#startManagedServer();

    const client = new ObservableMatterClient(this.settings.backendUrl, (event) => this.#handleRawEvent(event));
    this.#client = client;
    let lastError: unknown;
    for (let attempt = 0; attempt < 40; attempt += 1) {
      try {
        await client.connect();
        await client.startListening();
        this.#attachClientListeners(client);
        this.#connected = true;
        this.#emit("backend.connected", {});
        return;
      } catch (error) {
        lastError = error;
        await delay(250);
      }
    }
    await this.stop();
    throw new Error(`Matter.js server did not become ready: ${safeMessage(lastError)}`);
  }

  #attachClientListeners(client: MatterClient): void {
    client.addEventListener("connection_lost", () => {
      this.#connected = false;
      this.#emit("backend.connection_lost", {});
      if (!this.#stopping) this.#reconnecting ??= this.#reconnect(client).finally(() => { this.#reconnecting = undefined; });
    });
    client.addEventListener("server_shutdown", () => {
      this.#connected = false;
      this.#emit("backend.shutdown", {});
    });
  }

  async stop(): Promise<void> {
    this.#stopping = true;
    this.#connected = false;
    this.#client?.disconnect();
    this.#client = undefined;
    const child = this.#child;
    this.#child = undefined;
    if (child && child.exitCode === null) {
      child.kill("SIGTERM");
      await Promise.race([
        new Promise<void>((resolve) => child.once("exit", () => resolve())),
        delay(3000).then(() => undefined),
      ]);
      if (child.exitCode === null) child.kill("SIGKILL");
    }
  }

  async listNodes(): Promise<MatterNodeSnapshot[]> {
    return (await this.#requiredClient().getNodes()).map(toSnapshot);
  }

  async getNode(nodeId: string): Promise<MatterNodeSnapshot> {
    return toSnapshot(await this.#requiredClient().getNode(BigInt(nodeId)));
  }

  async discoverCommissionables(timeoutSeconds: number): Promise<MatterCommissionable[]> {
    const records = await this.#requiredClient().discoverCommissionableNodes(timeoutSeconds * 1000);
    return records.map((record) => ({
      ...(record.instance_name === undefined ? {} : { instanceName: record.instance_name }),
      ...(record.vendor_id === undefined ? {} : { vendorId: record.vendor_id }),
      ...(record.product_id === undefined ? {} : { productId: record.product_id }),
      ...(record.device_type === undefined ? {} : { deviceType: record.device_type }),
      ...(record.long_discriminator === undefined ? {} : { longDiscriminator: record.long_discriminator }),
      ...(record.commissioning_mode === undefined ? {} : { commissioningMode: record.commissioning_mode }),
      addresses: record.addresses ?? [],
    }));
  }

  async commissionWithCode(setupCode: string, networkOnly = false): Promise<MatterNodeSnapshot> {
    return toSnapshot(await this.#requiredClient().commissionWithCode(setupCode, networkOnly));
  }

  async setWifiCredentials(ssid: string, credentials: string): Promise<void> {
    await this.#requiredClient().setWifiCredentials(ssid, credentials);
  }

  async setThreadDataset(dataset: string): Promise<void> {
    await this.#requiredClient().setThreadOperationalDataset(dataset);
  }

  async clearWifiCredentials(): Promise<void> {
    await this.#requiredClient().removeWifiCredentials();
  }

  async clearThreadDataset(): Promise<void> {
    await this.#requiredClient().removeThreadDataset();
  }

  async removeNode(nodeId: string): Promise<void> {
    await this.#requiredClient().removeNode(BigInt(nodeId));
  }

  async invoke(nodeId: string, endpointId: number, command: string, args: JsonObject): Promise<unknown> {
    if (command === "refresh") {
      await this.getNode(nodeId);
      return { refreshed: true };
    }
    const matterCommand = { turn_on: "on", turn_off: "off", toggle: "toggle" }[command];
    if (!matterCommand) throw new Error(`Unsupported Matter command: ${command}`);
    if (Object.keys(args).length > 0) throw new Error(`${command} does not accept arguments`);
    return this.#requiredClient().deviceCommand(BigInt(nodeId), endpointId, 6, matterCommand, args);
  }

  onEvent(listener: (event: MatterEvent) => void): () => void {
    this.#listeners.add(listener);
    return () => this.#listeners.delete(listener);
  }

  #startManagedServer(): void {
    if (this.#child && this.#child.exitCode === null) return;
    const entrypoint = fileURLToPath(import.meta.resolve("matter-server"));
    const args = [
      entrypoint,
      "--storage-path", this.settings.storageDir,
      "--port", String(this.settings.backendPort),
      "--listen-address", this.settings.backendHost,
      "--disable-dashboard",
      "--disable-ota",
      "--default-fabric-label", "PiPhi Network",
    ];
    if (this.settings.enableBle) args.push("--bluetooth-adapter", "0");
    if (this.settings.primaryInterface) args.push("--primary-interface", this.settings.primaryInterface);
    this.#child = spawn(process.execPath, args, {
      stdio: ["ignore", "inherit", "inherit"],
      env: { ...process.env, NODE_ENV: "production" },
    });
    this.#child.once("exit", (code, signal) => {
      this.#connected = false;
      this.#emit("backend.exited", { code, signal });
      if (!this.#stopping && this.settings.manageBackend && this.#restartAttempts < 5) {
        this.#restartAttempts += 1;
        void delay(Math.min(this.#restartAttempts * 1000, 5000)).then(() => {
          if (!this.#stopping) this.#startManagedServer();
        });
      }
    });
  }

  #requiredClient(): MatterClient {
    if (!this.#connected || !this.#client) throw new Error("Matter.js backend is not connected");
    return this.#client;
  }

  async #reconnect(client: MatterClient): Promise<void> {
    for (let attempt = 0; attempt < 40 && !this.#stopping; attempt += 1) {
      try {
        await delay(Math.min(250 * (attempt + 1), 2000));
        await client.connect();
        await client.startListening();
        this.#connected = true;
        this.#restartAttempts = 0;
        this.#emit("backend.reconnected", {});
        return;
      } catch {
        // Retry with a bounded backoff; health remains degraded meanwhile.
      }
    }
    if (!this.#stopping) this.#emit("backend.reconnect_exhausted", {});
  }

  #handleRawEvent(event: EventMessage): void {
    if (event.event === "attribute_updated") {
      const [nodeId, path, value] = event.data;
      const [endpointId, clusterId, attributeId] = path.split("/").map(Number);
      if (endpointId === 0 || clusterId === undefined || sensitiveClusterIds.has(clusterId)) return;
      this.#emit("device.state_changed", {
        path,
        cluster_id: clusterId ?? null,
        attribute_id: attributeId ?? null,
        value: sanitize(value),
      }, String(nodeId), endpointId);
      return;
    }
    if (event.event === "node_event") {
      if (event.data.endpoint_id === 0 || sensitiveClusterIds.has(event.data.cluster_id)) return;
      this.#emit("matter.event", {
        cluster_id: event.data.cluster_id,
        event_id: event.data.event_id,
        event_number: String(event.data.event_number),
        priority: event.data.priority,
        data: sanitize(event.data.data),
      }, String(event.data.node_id), event.data.endpoint_id);
      return;
    }
    this.#emit(`matter.${event.event}`, { data: sanitize(event.data) });
  }

  #emit(type: string, payload: JsonObject, nodeId?: string, endpointId?: number): void {
    const event: MatterEvent = {
      id: randomUUID(),
      type,
      timestamp: new Date().toISOString(),
      ...(nodeId === undefined ? {} : { node_id: nodeId }),
      ...(endpointId === undefined ? {} : { endpoint_id: endpointId }),
      payload,
    };
    for (const listener of this.#listeners) listener(event);
  }
}

const sensitiveClusterIds = new Set([31, 49, 62, 63]);

class ObservableMatterClient extends MatterClient {
  constructor(url: string, private readonly listener: (event: EventMessage) => void) {
    super(url);
  }

  protected override onRawEvent(event: EventMessage): void {
    this.listener(event);
  }
}

function toSnapshot(node: MatterNode): MatterNodeSnapshot {
  return {
    nodeId: String(node.node_id),
    available: node.available,
    dateCommissioned: node.date_commissioned,
    ...(node.matter_version === undefined ? {} : { matterVersion: node.matter_version }),
    attributes: sanitize(node.attributes) as JsonObject,
  };
}

function sanitize(value: unknown): unknown {
  if (typeof value === "bigint") return value.toString();
  if (Array.isArray(value)) return value.map(sanitize);
  if (value && typeof value === "object") {
    return Object.fromEntries(Object.entries(value).map(([key, item]) => [key, sanitize(item)]));
  }
  return value;
}

function safeMessage(error: unknown): string {
  return error instanceof Error ? error.message : String(error ?? "unknown error");
}
