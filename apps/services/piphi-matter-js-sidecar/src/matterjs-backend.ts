import {
  MatterClient,
  type ClientLogger,
  type EventMessage,
  type MatterNode,
  type ServerInfoMessage,
} from "@matter-server/ws-client";
import { createHash, randomUUID } from "node:crypto";
import { spawn, type ChildProcess } from "node:child_process";
import { setTimeout as delay } from "node:timers/promises";
import { fileURLToPath } from "node:url";

import type { MatterSettings } from "./settings.js";
import { acquireStorageLease, type StorageLeaseRelease } from "./storage-lock.js";
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
  #releaseStorageLease: StorageLeaseRelease | undefined;
  #listeners = new Set<(event: MatterEvent) => void>();

  constructor(private readonly settings: MatterSettings) {}

  get connected(): boolean {
    return this.#connected;
  }

  diagnostics(): JsonObject {
    const serverInfo = this.#client?.serverInfo;
    return {
      connected: this.#connected,
      managed: this.settings.manageBackend,
      child_running: Boolean(this.#child && this.#child.exitCode === null),
      reconnecting: Boolean(this.#reconnecting),
      restart_attempts: this.#restartAttempts,
      storage_locked: Boolean(this.#releaseStorageLease),
      server: serverInfo ? {
        sdk_version: serverInfo.sdk_version,
        schema_version: serverInfo.schema_version,
        min_supported_schema_version: serverInfo.min_supported_schema_version,
        wifi_credentials_set: serverInfo.wifi_credentials_set,
        thread_credentials_set: serverInfo.thread_credentials_set,
        bluetooth_enabled: serverInfo.bluetooth_enabled,
        controller_identity_hash: controllerIdentityHash(serverInfo),
      } : null,
    };
  }

  async start(): Promise<void> {
    if (this.#connected) return;
    this.#stopping = false;
    this.#releaseStorageLease ??= await acquireStorageLease(this.settings.storageDir);
    if (this.settings.manageBackend) this.#startManagedServer();

    const client = new ObservableMatterClient(
      this.settings.backendUrl,
      (event) => this.#handleRawEvent(event),
      process.env.MATTER_CLIENT_DEBUG === "true" ? undefined : quietClientLogger,
    );
    this.#client = client;
    let lastError: unknown;
    for (let attempt = 0; attempt < 120; attempt += 1) {
      try {
        await client.connect();
        assertServerCompatibility(client.serverInfo);
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
      this.#scheduleReconnect(client);
    });
    client.addEventListener("server_shutdown", () => {
      this.#connected = false;
      this.#emit("backend.shutdown", {});
      this.#scheduleReconnect(client);
    });
  }

  #scheduleReconnect(client: MatterClient): void {
    if (!this.#stopping) {
      this.#reconnecting ??= this.#reconnect(client).finally(() => { this.#reconnecting = undefined; });
    }
  }

  async stop(): Promise<void> {
    await this.quiesce();
    const releaseStorageLease = this.#releaseStorageLease;
    this.#releaseStorageLease = undefined;
    await releaseStorageLease?.();
  }

  async quiesce(): Promise<void> {
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
        delay(10_000).then(() => undefined),
      ]);
      if (child.exitCode === null) child.kill("SIGKILL");
    }
  }

  async resume(): Promise<void> {
    await this.start();
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

  async commissionWithCode(setupCode: string, networkOnly = false, options: {
    wifiCredentialsId?: string;
    discoveryTimeoutSeconds?: number;
    timeoutMs?: number;
  } = {}): Promise<MatterNodeSnapshot> {
    return toSnapshot(await this.#requiredClient().commissionWithCode(setupCode, networkOnly, {
      ...(options.wifiCredentialsId ? { wifiCredentialsId: options.wifiCredentialsId } : {}),
      ...(options.discoveryTimeoutSeconds === undefined ? {} : { discoveryTimeoutS: options.discoveryTimeoutSeconds }),
      ...(options.timeoutMs === undefined ? {} : { timeout: options.timeoutMs }),
    }));
  }

  async setWifiCredentials(ssid: string, credentials: string, id?: string): Promise<void> {
    await this.#requiredClient().setWifiCredentials(ssid, credentials, id ? { id } : undefined);
  }

  async setThreadDataset(dataset: string): Promise<void> {
    await this.#requiredClient().setThreadOperationalDataset(dataset);
  }

  async clearWifiCredentials(id?: string): Promise<void> {
    await this.#requiredClient().removeWifiCredentials(id ? { id } : undefined);
  }

  async clearTemporaryWifiCredentials(prefix: string): Promise<number> {
    const credentials = await this.#requiredClient().getAllCredentials();
    const ids = credentials.wifi.map(({ id }) => id).filter((id) => id.startsWith(prefix));
    for (const id of ids) await this.#requiredClient().removeWifiCredentials({ id });
    return ids.length;
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
    if (this.settings.dclOffline) args.push("--dcl-offline");
    if (this.settings.enableBle) args.push("--bluetooth-adapter", "0");
    if (this.settings.primaryInterface) args.push("--primary-interface", this.settings.primaryInterface);
    this.#child = spawn(process.execPath, args, {
      stdio: ["ignore", this.settings.logManagedServer ? "inherit" : "ignore", this.settings.logManagedServer ? "inherit" : "ignore"],
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
        assertServerCompatibility(client.serverInfo);
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
    const publicEvent = toPublicMatterEvent(event);
    if (!publicEvent) return;
    this.#emit(publicEvent.type, publicEvent.payload, publicEvent.nodeId, publicEvent.endpointId);
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

function controllerIdentityHash(serverInfo: ServerInfoMessage): string {
  return createHash("sha256")
    .update(`${String(serverInfo.fabric_id)}:${String(serverInfo.compressed_fabric_id)}`)
    .digest("hex")
    .slice(0, 16);
}

const sensitiveClusterIds = new Set([31, 49, 62, 63]);
const minimumSupportedServerSchema = 13;
const maximumSupportedServerSchema = 15;

export function assertServerCompatibility(serverInfo: ServerInfoMessage): void {
  if (serverInfo.schema_version < minimumSupportedServerSchema
    || serverInfo.min_supported_schema_version > maximumSupportedServerSchema) {
    throw new Error(
      `Unsupported Matter Server WebSocket schema ${serverInfo.schema_version} `
      + `(server minimum ${serverInfo.min_supported_schema_version}); `
      + `PiPhi supports ${minimumSupportedServerSchema}-${maximumSupportedServerSchema}.`,
    );
  }
}

interface PublicMatterEvent {
  type: string;
  payload: JsonObject;
  nodeId?: string;
  endpointId?: number;
}

export function toPublicMatterEvent(event: EventMessage): PublicMatterEvent | undefined {
  if (event.event === "attribute_updated") {
    const [nodeId, path, value] = event.data;
    const [endpointId, clusterId, attributeId] = path.split("/").map(Number);
    if (endpointId === undefined || !Number.isInteger(endpointId) || endpointId === 0
      || clusterId === undefined || sensitiveClusterIds.has(clusterId)) return undefined;
    return {
      type: "device.state_changed",
      nodeId: String(nodeId),
      endpointId,
      payload: {
        path,
        cluster_id: clusterId,
        attribute_id: attributeId ?? null,
        value: sanitize(value),
      },
    };
  }
  if (event.event === "node_event") {
    if (event.data.endpoint_id === 0 || sensitiveClusterIds.has(event.data.cluster_id)) return undefined;
    return {
      type: "matter.event",
      nodeId: String(event.data.node_id),
      endpointId: event.data.endpoint_id,
      payload: {
        cluster_id: event.data.cluster_id,
        event_id: event.data.event_id,
        event_number: String(event.data.event_number),
        priority: event.data.priority,
        data: sanitize(event.data.data),
      },
    };
  }
  if (event.event === "node_added" || event.event === "node_updated") {
    const data = event.data as MatterNode;
    return {
      type: `matter.${event.event}`,
      nodeId: String(data.node_id),
      payload: {
        available: data.available,
        date_commissioned: data.date_commissioned,
        is_bridge: data.is_bridge,
      },
    };
  }
  if (event.event === "node_removed") {
    return { type: "matter.node_removed", nodeId: String(event.data), payload: {} };
  }
  if (event.event === "endpoint_added" || event.event === "endpoint_removed") {
    return {
      type: `matter.${event.event}`,
      nodeId: String(event.data.node_id),
      endpointId: event.data.endpoint_id,
      payload: {},
    };
  }
  if (event.event === "server_shutdown") {
    return { type: "matter.server_shutdown", payload: {} };
  }
  if (event.event === "server_info_updated") {
    const data = event.data;
    return {
      type: "matter.server_info_updated",
      payload: {
        schema_version: data.schema_version,
        min_supported_schema_version: data.min_supported_schema_version,
        sdk_version: data.sdk_version,
        wifi_credentials_set: data.wifi_credentials_set,
        thread_credentials_set: data.thread_credentials_set,
        bluetooth_enabled: data.bluetooth_enabled,
      },
    };
  }
  return undefined;
}

class ObservableMatterClient extends MatterClient {
  constructor(
    url: string,
    private readonly listener: (event: EventMessage) => void,
    logger?: ClientLogger,
  ) {
    super(url, logger === undefined ? undefined : { logger });
  }

  protected override onRawEvent(event: EventMessage): void {
    this.listener(event);
  }
}

const quietClientLogger: ClientLogger = {
  debug: () => undefined,
  info: () => undefined,
  warn: () => undefined,
  error: () => undefined,
};

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
