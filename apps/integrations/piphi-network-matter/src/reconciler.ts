import { projectNodes } from "./capabilities.js";
import type { ConfigStore } from "./config-store.js";
import type { CoreClient } from "./core-client.js";
import type { SidecarClient } from "./sidecar-client.js";
import type { ProjectedEntity, SidecarSnapshot } from "./types.js";

export class Reconciler {
  readonly #entities = new Map<string, ProjectedEntity>();
  #cursor = 0;
  #streamId: string | undefined;
  #timer: NodeJS.Timeout | undefined;
  #lastError: string | undefined;
  #lastDeliveryError: string | undefined;
  #lastReconciledAt: string | undefined;
  #consecutiveFailures = 0;
  #nextRetryAt: string | undefined;

  constructor(
    private readonly sidecar: SidecarClient,
    private readonly configs: ConfigStore,
    private readonly core: CoreClient,
    private readonly intervalMs: number,
  ) {}

  entities(): ProjectedEntity[] { return [...this.#entities.values()].sort((a, b) => a.id.localeCompare(b.id)); }
  status() {
    return {
      connected: !this.#lastError,
      stream_id: this.#streamId ?? null,
      cursor: this.#cursor,
      last_reconciled_at: this.#lastReconciledAt ?? null,
      last_error: this.#lastError ? "sidecar_unavailable" : null,
      delivery_error: this.#lastDeliveryError ? "core_delivery_failed" : null,
      entity_count: this.#entities.size,
      stale: Boolean(this.#lastError && this.#lastReconciledAt),
      consecutive_failures: this.#consecutiveFailures,
      next_retry_at: this.#nextRetryAt ?? null,
    };
  }

  async start(): Promise<void> {
    await this.configs.load();
    try {
      await this.fullSnapshot();
    } catch (error) {
      this.#lastError = error instanceof Error ? error.message : String(error);
    }
    this.#schedulePoll(this.intervalMs);
  }

  stop(): void { if (this.#timer) clearInterval(this.#timer); this.#timer = undefined; }

  async fullSnapshot(): Promise<void> {
    const changed = this.#applySnapshot(await this.sidecar.snapshot());
    try {
      await Promise.all(changed.flatMap(({ entity, previous }) => [
        this.core.telemetry(entity),
        ...(previous ? [this.core.stateChanged(entity, previous.state)] : []),
      ]));
      this.#lastDeliveryError = undefined;
    } catch (error) {
      this.#lastDeliveryError = error instanceof Error ? error.message : String(error);
    }
  }

  async poll(): Promise<void> {
    try {
      const page = await this.sidecar.events(this.#cursor);
      if (page.stream_id !== this.#streamId || page.gap) {
        await this.fullSnapshot();
        return;
      }
      if (page.events.length > 0) await this.fullSnapshot();
      else this.#cursor = page.next_cursor;
      this.#lastError = undefined;
      this.#consecutiveFailures = 0;
      this.#nextRetryAt = undefined;
    } catch (error) {
      this.#lastError = error instanceof Error ? error.message : String(error);
      this.#consecutiveFailures += 1;
      throw error;
    }
  }

  async deliverTelemetry(): Promise<Array<{ entity_id: string; delivery: string }>> {
    return Promise.all(this.entities().map(async (entity) => ({ entity_id: entity.id, delivery: await this.core.telemetry(entity) })));
  }

  #applySnapshot(snapshot: SidecarSnapshot): Array<{ entity: ProjectedEntity; previous?: ProjectedEntity }> {
    const next = new Map<string, ProjectedEntity>();
    const entities = projectNodes(snapshot.nodes, snapshot.controller.identity_hash, (nodeId, endpointId) => {
      return this.configs.get(snapshot.controller.identity_hash, nodeId, endpointId)?.alias;
    });
    for (const entity of entities) {
      const config = this.configs.get(
        entity.metadata.controller_identity_hash,
        entity.metadata.node_id,
        entity.metadata.endpoint_id,
      );
      if (config?.enabled !== false) next.set(entity.id, entity);
    }
    const changed = [...next.values()].flatMap((entity) => {
      const previous = this.#entities.get(entity.id);
      if (previous !== undefined && JSON.stringify(previous.state) === JSON.stringify(entity.state)) return [];
      return [{ entity, ...(previous ? { previous } : {}) }];
    });
    this.#entities.clear();
    for (const [id, entity] of next) this.#entities.set(id, entity);
    this.#streamId = snapshot.stream_id;
    this.#cursor = snapshot.latest_sequence;
    this.#lastReconciledAt = new Date().toISOString();
    this.#lastError = undefined;
    this.#consecutiveFailures = 0;
    this.#nextRetryAt = undefined;
    return changed;
  }

  #schedulePoll(delayMs: number): void {
    if (this.#timer) clearTimeout(this.#timer);
    this.#nextRetryAt = new Date(Date.now() + delayMs).toISOString();
    this.#timer = setTimeout(async () => {
      try { await this.poll(); } catch { /* Last-good state remains available while health is degraded. */ }
      const backoff = Math.min(this.intervalMs * (2 ** Math.min(this.#consecutiveFailures, 5)), 60_000);
      this.#schedulePoll(backoff);
    }, delayMs);
    this.#timer.unref();
  }
}
