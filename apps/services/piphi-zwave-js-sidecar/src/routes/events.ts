import type { FastifyInstance } from "fastify";
import { buildEventIngestResponse, buildEventListResponse } from "piphi-runtime-kit-node";

import { integrationId } from "../settings.js";
import { appendRuntimeEvent, readZWaveEvents, registry, runtime } from "../state.js";

export function registerEventRoutes(app: FastifyInstance): void {
  app.get("/events", async () => {
    return buildEventListResponse(registry.recentEvents);
  });

  app.get("/v1/zwave/events", async (request, reply) => {
    const query = request.query as { after?: string; limit?: string };
    const after = query.after == null ? 0 : Number(query.after);
    const limit = query.limit == null ? 100 : Number(query.limit);
    if (!Number.isInteger(after) || after < 0 || !Number.isInteger(limit) || limit < 1 || limit > 500) {
      return reply.code(400).send({ ok: false, reason: "after and limit must be bounded integers" });
    }
    return readZWaveEvents(after, limit);
  });

  app.post("/events/example", async () => {
    const entry = registry.primaryEntry();
    const event = appendRuntimeEvent(
      "runtime.event",
      {
        deviceId: entry?.deviceId ?? "zwave-js-service",
        configId: entry?.configId ?? "zwave-js-service",
        containerId: entry?.containerId ?? runtime.auth.containerId ?? null,
        integrationId: entry?.integrationId ?? integrationId,
      },
      { message: "Example local runtime event" },
    );
    return buildEventIngestResponse(event);
  });

  app.post("/events/device/:configId/example", async (request, reply) => {
    const { configId } = request.params as { configId: string };
    const entry = registry.get(configId);
    if (!entry) {
      return reply.code(404).send({ ok: false, reason: `unknown config_id=${configId}` });
    }
    const event = appendRuntimeEvent("runtime.device.checked", entry, {
      message: "Example local runtime event for a configured device",
      controller_path_configured: true,
    });
    return buildEventIngestResponse(event);
  });
}
