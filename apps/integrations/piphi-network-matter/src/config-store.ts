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
    this.#items.set(key(item.controller_identity_hash, item.node_id, item.endpoint_id), normalized);
    await this.save();
    return normalized;
  }

  async removeNode(nodeId: string, controllerIdentityHash?: string): Promise<number> {
    let removed = 0;
    for (const [itemKey, item] of this.#items) {
      if (item.node_id !== nodeId
        || (controllerIdentityHash !== undefined && item.controller_identity_hash !== controllerIdentityHash)) continue;
      this.#items.delete(itemKey);
      removed += 1;
    }
    if (removed > 0) await this.save();
    return removed;
  }

  private async save(): Promise<void> {
    await mkdir(dirname(this.path), { recursive: true, mode: 0o700 });
    const temporary = `${this.path}.tmp`;
    await writeFile(temporary, `${JSON.stringify(this.list(), null, 2)}\n`, { mode: 0o600 });
    await rename(temporary, this.path);
  }
}
