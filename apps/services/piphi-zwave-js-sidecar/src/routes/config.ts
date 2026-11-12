import type { FastifyInstance } from "fastify";
import {
  buildConfigApplyResponse,
  buildConfigRemoveResponse,
  type RuntimeConfigSnapshot,
} from "piphi-runtime-kit-node";
import { syncRuntimeAuthFromFastifyRequest } from "piphi-runtime-kit-node/adapters/fastify";

import { applyConfig, configSync, registry, removeConfig, runtime } from "../state.js";
import type { DeviceConfig } from "../types.js";

export function registerConfigRoutes(app: FastifyInstance): void {
  app.post("/config", async (request) => {
    const payload = request.body as DeviceConfig;
    syncRuntimeAuthFromFastifyRequest(runtime, request, payload.containerId);
    await applyConfig(payload);
    return buildConfigApplyResponse({
      configId: payload.configId ?? payload.id,
      containerId: payload.containerId,
      metadata: {
        host: payload.host,
        alias: payload.alias ?? null,
      },
    });
  });

  app.post("/config/sync", async (request) => {
    const snapshot = request.body as RuntimeConfigSnapshot<DeviceConfig>;
    syncRuntimeAuthFromFastifyRequest(runtime, request, snapshot.containerId);
    return configSync.applySnapshot(snapshot, {
      activeConfigIds: registry.ids(),
      applyConfig,
      removeConfig,
      getActiveConfigIds: () => registry.ids(),
    });
  });

  app.post("/deconfigure", async (request) => {
    const payload = (request.body ?? {}) as { config_id?: string; configId?: string };
    const configId = payload.config_id ?? payload.configId;
    if (!configId) {
      return { ok: false, reason: "missing config_id" };
    }
    const removed = await removeConfig(configId);
    return buildConfigRemoveResponse({
      configId,
      removed,
    });
  });

  app.post("/deconfigure/:configId", async (request) => {
    const { configId } = request.params as { configId: string };
    const removed = await removeConfig(configId);
    return buildConfigRemoveResponse({
      configId,
      removed,
    });
  });
}
