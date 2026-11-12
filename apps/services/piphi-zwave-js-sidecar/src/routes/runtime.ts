import type { FastifyInstance } from "fastify";

import { endpoints, requiredEndpoints } from "../contract.js";
import { integrationId, integrationName, integrationVersion, projectDomain, projectKind, projectPreset } from "../settings.js";
import { registry, starter } from "../state.js";

export function registerRuntimeRoutes(app: FastifyInstance): void {
  app.get("/state", async (request, reply) => {
    const query = request.query as { refresh?: string | boolean; refresh_request_id?: string };
    const refresh = query.refresh === true || query.refresh === "true";
    if (refresh && !query.refresh_request_id) {
      return reply.code(400).send({ detail: "refresh_request_id is required when refresh=true" });
    }
    const options: { refresh: boolean; refreshRequestId?: string } = { refresh };
    if (query.refresh_request_id) options.refreshRequestId = query.refresh_request_id;
    const statePayload = await starter.state.response(options);
    return {
      ...statePayload,
      summary: {
        activeConfigCount: registry.ids().length,
        recentEventCount: registry.recentEvents.length,
      },
      runtimeEntries: Object.fromEntries(registry.entries),
      stateSnapshots: Object.fromEntries(registry.stateSnapshots),
    };
  });

  app.get("/contract", async () => {
    return {
      integration_id: integrationId,
      name: integrationName,
      version: integrationVersion,
      kind: projectKind,
      preset: projectPreset,
      domain: projectDomain,
      endpoints,
      required: requiredEndpoints,
    };
  });
}
