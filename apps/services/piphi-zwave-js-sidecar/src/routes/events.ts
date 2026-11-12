import type { FastifyInstance } from "fastify";
import { buildEventIngestResponse, buildEventListResponse } from "piphi-runtime-kit-node";

import { integrationId } from "../settings.js";
import { appendRuntimeEvent, registry, runtime } from "../state.js";

export function registerEventRoutes(app: FastifyInstance): void {
  app.get("/events", async () => {
    return buildEventListResponse(registry.recentEvents);
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
      host: entry.host,
    });
    return buildEventIngestResponse(event);
  });
}
