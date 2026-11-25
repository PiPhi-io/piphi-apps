import { mkdir, readFile, rename, writeFile } from "node:fs/promises";
import { dirname } from "node:path";
import type { EndpointConfig } from "./types.js";

const key = (controllerIdentityHash: string, nodeId: string, endpointId: number) => (
  `${controllerIdentityHash}:${nodeId}:${endpointId}`
);

export class ConfigStore {
  readonly #items = new Map<string, EndpointConfig>();
  constructor(private readonly path: string) {}

  async load(): Promise<void> {
    try {
      const items = JSON.parse(await readFile(this.path, "utf8")) as EndpointConfig[];
      for (const item of items) {
        if (!item.controller_identity_hash || !item.node_id || !Number.isInteger(item.endpoint_id)) continue;
        this.#items.set(key(item.controller_identity_hash, item.node_id, item.endpoint_id), item);
      }
    } catch (error) {
      if ((error as NodeJS.ErrnoException).code !== "ENOENT") throw error;
    }
  }

  list(): EndpointConfig[] { return [...this.#items.values()]; }
  get(controllerIdentityHash: string, nodeId: string, endpointId: number): EndpointConfig | undefined {
    return this.#items.get(key(controllerIdentityHash, nodeId, endpointId));
  }

  async set(item: EndpointConfig): Promise<EndpointConfig> {
    const normalized: EndpointConfig = {
      controller_identity_hash: item.controller_identity_hash,
      node_id: item.node_id,
      endpoint_id: item.endpoint_id,
      enabled: item.enabled,
      ...(item.alias?.trim() ? { alias: item.alias.trim() } : {}),
    };
    const next = new Map(this.#items);
    next.set(key(item.controller_identity_hash, item.node_id, item.endpoint_id), normalized);
    await this.save(next);
    this.#replace(next);
    return normalized;
  }

  async removeNode(nodeId: string, controllerIdentityHash?: string): Promise<number> {
    let removed = 0;
    const next = new Map(this.#items);
    for (const [itemKey, item] of next) {
      if (item.node_id !== nodeId
        || (controllerIdentityHash !== undefined && item.controller_identity_hash !== controllerIdentityHash)) continue;
      next.delete(itemKey);
      removed += 1;
    }
    if (removed > 0) { await this.save(next); this.#replace(next); }
    return removed;
  }

  async delete(controllerIdentityHash: string, nodeId: string, endpointId: number): Promise<boolean> {
    const next = new Map(this.#items);
    const removed = next.delete(key(controllerIdentityHash, nodeId, endpointId));
    if (removed) { await this.save(next); this.#replace(next); }
    return removed;
  }

  async replaceAll(items: EndpointConfig[]): Promise<void> {
    const next = new Map(items.map((item) => [key(item.controller_identity_hash, item.node_id, item.endpoint_id), item]));
    await this.save(next);
    this.#replace(next);
  }

  private async save(items: Map<string, EndpointConfig>): Promise<void> {
    await mkdir(dirname(this.path), { recursive: true, mode: 0o700 });
    const temporary = `${this.path}.tmp`;
    await writeFile(temporary, `${JSON.stringify([...items.values()], null, 2)}\n`, { mode: 0o600 });
    await rename(temporary, this.path);
  }

  #replace(items: Map<string, EndpointConfig>): void {
    this.#items.clear();
    for (const [itemKey, item] of items) this.#items.set(itemKey, item);
  }
}
