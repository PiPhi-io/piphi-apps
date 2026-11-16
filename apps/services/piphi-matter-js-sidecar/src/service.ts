import { randomUUID } from "node:crypto";
import { mkdir, readFile, rename, writeFile } from "node:fs/promises";
import { join } from "node:path";

import { isSupportedCommand, normalizeNode } from "./capabilities.js";
import { EventCursorExpiredError, MatterEventJournal } from "./event-journal.js";
import type { MatterSettings } from "./settings.js";
import type {
  ConfiguredEndpoint,
  JsonObject,
  MatterBackend,
  MatterEndpoint,
  MatterEvent,
} from "./types.js";

export class MatterSidecarService {
  readonly #configs = new Map<string, ConfiguredEndpoint>();
  readonly #eventJournal = new MatterEventJournal();
  #startedAt: string | undefined;
  #lastError: string | undefined;
  #unsubscribe: (() => void) | undefined;
  #backupQuiesced = false;
  #wifiProvisioning = false;

  constructor(
    readonly backend: MatterBackend,
    readonly settings: MatterSettings,
  ) {}

  async start(): Promise<void> {
    if (this.#startedAt) return;
    await this.#loadConfigs();
    this.#unsubscribe = this.backend.onEvent((event) => this.#recordEvent(event));
    try {
      await this.backend.start();
      await this.backend.clearTemporaryWifiCredentials("piphi-provision-");
      this.#startedAt = new Date().toISOString();
      this.#lastError = undefined;
    } catch (error) {
      this.#lastError = safeMessage(error);
      throw error;
    }
  }

  async stop(): Promise<void> {
    this.#unsubscribe?.();
    this.#unsubscribe = undefined;
    await this.backend.stop();
    this.#startedAt = undefined;
    this.#backupQuiesced = false;
  }

  async quiesceForBackup(): Promise<JsonObject> {
    if (this.#backupQuiesced) return { quiesced: true, already_quiesced: true };
    await this.backend.quiesce();
    this.#backupQuiesced = true;
    this.#recordEvent({
      id: randomUUID(),
      type: "backend.backup_quiesced",
      timestamp: new Date().toISOString(),
      payload: {},
    });
    return { quiesced: true, already_quiesced: false };
  }

  async resumeAfterBackup(): Promise<JsonObject> {
    if (!this.#backupQuiesced) return { resumed: true, already_running: this.backend.connected };
    await this.backend.resume();
    this.#backupQuiesced = false;
    this.#recordEvent({
      id: randomUUID(),
      type: "backend.backup_resumed",
      timestamp: new Date().toISOString(),
      payload: {},
    });
    return { resumed: true, already_running: false };
  }

  snapshot(): JsonObject {
    return {
      running: Boolean(this.#startedAt),
      backend_connected: this.backend.connected,
      backend: "matterjs-server",
      backend_details: this.backend.diagnostics(),
      started_at: this.#startedAt ?? null,
      configured_endpoint_count: this.#configs.size,
      queued_event_count: this.#eventJournal.size,
      dropped_event_count: this.#eventJournal.dropped,
      event_stream_id: this.#eventJournal.streamId,
      latest_event_sequence: this.#eventJournal.latestSequence,
      backup_quiesced: this.#backupQuiesced,
      last_error: this.#lastError ?? null,
    };
  }

  async discover(nodeId?: string): Promise<MatterEndpoint[]> {
    const nodes = nodeId ? [await this.backend.getNode(nodeId)] : await this.backend.listNodes();
    return nodes.flatMap(normalizeNode);
  }

  async discoverCommissionables(timeoutSeconds: number) {
    return this.backend.discoverCommissionables(timeoutSeconds);
  }

  async commission(setupCode: string, networkOnly = false): Promise<MatterEndpoint[]> {
    if (!setupCode.trim()) throw new Error("setup_payload is required");
    const node = await this.backend.commissionWithCode(setupCode.trim(), networkOnly);
    const endpoints = normalizeNode(node);
    for (const endpoint of endpoints) {
      await this.configure(endpoint.nodeId, endpoint.endpointId);
    }
    return endpoints;
  }

  async provisionWifi(setupCode: string, ssid: string, credentials: string): Promise<MatterEndpoint[]> {
    if (!this.settings.enableBle) throw statusError(503, "ble_commissioning_disabled");
    if (!setupCode.trim()) throw statusError(400, "setup_payload_required");
    if (!validSsid(ssid)) throw statusError(400, "wifi_ssid_invalid");
    if (!credentials || Buffer.byteLength(credentials, "utf8") > 256) {
      throw statusError(400, "wifi_credentials_invalid");
    }
    if (this.#wifiProvisioning) throw statusError(409, "wifi_provisioning_in_progress");

    this.#wifiProvisioning = true;
    const credentialId = `piphi-provision-${randomUUID()}`;
    let stored = false;
    let operationFailed = false;
    try {
      await this.backend.setWifiCredentials(ssid, credentials, credentialId);
      stored = true;
      const node = await this.backend.commissionWithCode(setupCode.trim(), false, {
        wifiCredentialsId: credentialId,
        discoveryTimeoutSeconds: 180,
        timeoutMs: 300_000,
      });
      const endpoints = normalizeNode(node);
      for (const endpoint of endpoints) await this.configure(endpoint.nodeId, endpoint.endpointId);
      return endpoints;
    } catch (error) {
      operationFailed = true;
      throw error;
    } finally {
      try {
        if (stored) await this.backend.clearWifiCredentials(credentialId);
      } catch {
        this.#lastError = "Temporary Wi-Fi credential cleanup failed";
        if (!operationFailed) throw statusError(500, "wifi_credential_cleanup_failed");
      } finally {
        this.#wifiProvisioning = false;
      }
    }
  }

  async listRegistry(): Promise<JsonObject[]> {
    return (await this.discover()).map((endpoint) => ({
      node_id: endpoint.nodeId,
      endpoint_id: endpoint.endpointId,
      name: endpoint.name,
      device_types: endpoint.deviceTypes,
      capabilities: endpoint.capabilities,
      command_bindings: endpoint.commandBindings,
    }));
  }

  async removeNode(nodeId: string): Promise<void> {
    await this.backend.removeNode(nodeId);
    for (const key of [...this.#configs.keys()]) {
      if (key.startsWith(`${nodeId}:`)) this.#configs.delete(key);
    }
    await this.#saveConfigs();
  }

  listConfigs(): ConfiguredEndpoint[] {
    return [...this.#configs.values()].sort((a, b) => keyFor(a.node_id, a.endpoint_id).localeCompare(keyFor(b.node_id, b.endpoint_id)));
  }

  async configure(nodeId: string, endpointId: number, alias?: string): Promise<ConfiguredEndpoint> {
    const endpoint = (await this.discover(nodeId)).find((item) => item.endpointId === endpointId);
    if (!endpoint) throw new Error(`Matter endpoint ${nodeId}/${endpointId} was not found`);
    const configured: ConfiguredEndpoint = {
      node_id: nodeId,
      endpoint_id: endpointId,
      ...(alias?.trim() ? { alias: alias.trim() } : {}),
      enabled: true,
      preferred_source: "matter",
    };
    this.#configs.set(keyFor(nodeId, endpointId), configured);
    await this.#saveConfigs();
    return configured;
  }

  async removeConfig(nodeId: string, endpointId: number): Promise<boolean> {
    const removed = this.#configs.delete(keyFor(nodeId, endpointId));
    if (removed) await this.#saveConfigs();
    return removed;
  }

  async telemetry(): Promise<JsonObject[]> {
    const endpoints = await this.discover();
    const byKey = new Map(endpoints.map((endpoint) => [keyFor(endpoint.nodeId, endpoint.endpointId), endpoint]));
    const sampledAt = new Date().toISOString();
    return this.listConfigs().filter((config) => config.enabled).map((config) => {
      const endpoint = byKey.get(keyFor(config.node_id, config.endpoint_id));
      if (!endpoint) {
        return { ...config, config_key: keyFor(config.node_id, config.endpoint_id), read_failed: true, sampled_at: sampledAt, error: "Endpoint unavailable" };
      }
      return { ...config, config_key: keyFor(config.node_id, config.endpoint_id), read_failed: false, sampled_at: sampledAt, state: endpoint.state };
    });
  }

  async entities(): Promise<JsonObject> {
    const endpoints = await this.discover();
    return {
      entities: endpoints.map((endpoint) => ({
        id: keyFor(endpoint.nodeId, endpoint.endpointId),
        device_id: keyFor(endpoint.nodeId, endpoint.endpointId),
        name: this.#configs.get(keyFor(endpoint.nodeId, endpoint.endpointId))?.alias ?? endpoint.name,
        device_class: deviceClass(endpoint.capabilities),
        capabilities: endpoint.capabilities,
        available_commands: endpoint.commandBindings,
        state: endpoint.state,
        metadata: endpoint.metadata,
      })),
    };
  }

  async invoke(nodeId: string, endpointId: number, command: string, args: JsonObject): Promise<JsonObject> {
    if (!isSupportedCommand(command)) throw new Error(`Unsupported command: ${command}`);
    const endpoint = (await this.discover(nodeId)).find((item) => item.endpointId === endpointId);
    if (!endpoint) throw new Error(`Matter endpoint ${nodeId}/${endpointId} was not found`);
    if (!endpoint.commandBindings.includes(command)) throw new Error(`Command ${command} is unavailable for ${nodeId}/${endpointId}`);
    if (command !== "refresh" && Object.keys(args).length > 0) throw new Error(`${command} does not accept arguments`);
    const result = await this.backend.invoke(nodeId, endpointId, command, args);
    return { ok: true, node_id: nodeId, endpoint_id: endpointId, command, result: result ?? null };
  }

  events(after?: string): MatterEvent[] {
    return this.#eventJournal.legacyEvents(after);
  }

  eventPage(after?: string): JsonObject {
    const events = this.events(after);
    return {
      events,
      oldest_cursor: events[0]?.id ?? null,
      latest_cursor: events.at(-1)?.id ?? null,
      dropped_event_count: this.#eventJournal.dropped,
    };
  }

  transportEvents(after: number, limit: number): JsonObject {
    return this.#eventJournal.page(after, limit);
  }

  async transportSnapshot(): Promise<JsonObject> {
    const nodes = (await this.backend.listNodes()).map(publicNodeSnapshot);
    const backendDetails = this.backend.diagnostics();
    const server = backendDetails.server && typeof backendDetails.server === "object"
      ? backendDetails.server as JsonObject
      : {};
    return {
      schema_version: "piphi.matter.snapshot.v1",
      generated_at: new Date().toISOString(),
      stream_id: this.#eventJournal.streamId,
      latest_sequence: this.#eventJournal.latestSequence,
      dropped_event_count: this.#eventJournal.dropped,
      controller: {
        connected: this.backend.connected,
        identity_hash: server.controller_identity_hash ?? null,
        sdk_version: server.sdk_version ?? null,
        schema_version: server.schema_version ?? null,
      },
      nodes,
    };
  }

  #recordEvent(event: MatterEvent): void {
    this.#eventJournal.append(event);
  }

  get #configPath(): string {
    return join(this.settings.storageDir, "piphi-configured-endpoints.json");
  }

  async #loadConfigs(): Promise<void> {
    try {
      const records = JSON.parse(await readFile(this.#configPath, "utf8")) as ConfiguredEndpoint[];
      for (const record of records) this.#configs.set(keyFor(record.node_id, record.endpoint_id), record);
    } catch (error) {
      if ((error as NodeJS.ErrnoException).code !== "ENOENT") throw error;
    }
  }

  async #saveConfigs(): Promise<void> {
    await mkdir(this.settings.storageDir, { recursive: true, mode: 0o700 });
    const temporary = `${this.#configPath}.tmp`;
    await writeFile(temporary, `${JSON.stringify(this.listConfigs(), null, 2)}\n`, { mode: 0o600 });
    await rename(temporary, this.#configPath);
  }
}

export { EventCursorExpiredError };

function publicNodeSnapshot(node: Awaited<ReturnType<MatterBackend["listNodes"]>>[number]): JsonObject {
  const attributes = Object.fromEntries(
    Object.entries(node.attributes).filter(([path]) => isPublicAttributePath(path)),
  );
  return {
    node_id: node.nodeId,
    available: node.available,
    date_commissioned: node.dateCommissioned ?? null,
    matter_version: node.matterVersion ?? null,
    attributes,
  };
}

function isPublicAttributePath(path: string): boolean {
  const [endpointId, clusterId, attributeId] = path.split("/").map(Number);
  if (endpointId === 0 && clusterId === 40) {
    // Public Basic Information identity and version fields only. Location, serial number,
    // unique ID, capability minima, and product URLs remain private.
    return [1, 2, 3, 4, 5, 7, 8, 9, 10].includes(attributeId ?? -1);
  }
  if (endpointId === undefined || endpointId < 1 || clusterId === undefined || attributeId === undefined) return false;
  return new Set([
    "29/0", "29/1", "29/2", "29/3",
    "6/0", "8/0", "47/12", "69/0",
    "1024/0", "1026/0", "1029/0", "1030/0",
  ]).has(`${clusterId}/${attributeId}`);
}

function keyFor(nodeId: string, endpointId: number): string {
  return `${nodeId}:${endpointId}`;
}

function deviceClass(capabilities: string[]): string {
  if (capabilities.includes("switch_on")) return "switch";
  if (capabilities.includes("temperature_c") || capabilities.includes("humidity_percent")) return "sensor";
  if (capabilities.includes("contact_open")) return "binary_sensor";
  return "matter_device";
}

function safeMessage(error: unknown): string {
  return error instanceof Error ? error.message : String(error ?? "unknown error");
}

function validSsid(ssid: string): boolean {
  const bytes = Buffer.byteLength(ssid, "utf8");
  return ssid.trim() === ssid && bytes >= 1 && bytes <= 32;
}

function statusError(statusCode: number, message: string): Error & { statusCode: number } {
  return Object.assign(new Error(message), { statusCode });
}
