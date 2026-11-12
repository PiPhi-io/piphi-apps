import { mkdir, readFile, rename, writeFile } from "node:fs/promises";
import { join } from "node:path";

import { isSupportedCommand, normalizeNode } from "./capabilities.js";
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
  readonly #events: MatterEvent[] = [];
  #startedAt: string | undefined;
  #lastError: string | undefined;
  #unsubscribe: (() => void) | undefined;

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
  }

  snapshot(): JsonObject {
    return {
      running: Boolean(this.#startedAt),
      backend_connected: this.backend.connected,
      backend: "matterjs-server",
      started_at: this.#startedAt ?? null,
      configured_endpoint_count: this.#configs.size,
      queued_event_count: this.#events.length,
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
    if (!after) return [...this.#events];
    const index = this.#events.findIndex((event) => event.id === after);
    return index < 0 ? [...this.#events] : this.#events.slice(index + 1);
  }

  #recordEvent(event: MatterEvent): void {
    this.#events.push(event);
    if (this.#events.length > 1000) this.#events.splice(0, this.#events.length - 1000);
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
