import type { FastifyInstance } from "fastify";
import { scheduleTelemetryDelivery } from "piphi-runtime-kit-node";
import { syncRuntimeAuthFromFastifyRequest } from "piphi-runtime-kit-node/adapters/fastify";

import { registry, runtime, telemetry } from "../state.js";
import type { DeviceEntry } from "../types.js";

function queueTelemetry(entry: DeviceEntry): void {
  scheduleTelemetryDelivery({
    processState: runtime.processState,
    telemetryClient: telemetry,
    authContext: runtime.auth,
    configId: entry.configId,
    deviceId: entry.deviceId,
    containerId: entry.containerId,
    metrics: { connected: true },
    units: {},
  });
}

export function registerTelemetryRoutes(app: FastifyInstance): void {
  app.post("/telemetry/example", async (request, reply) => {
    syncRuntimeAuthFromFastifyRequest(runtime, request);
    const entry = registry.primaryEntry();
    if (!entry) {
      return reply.code(409).send({ ok: false, reason: "no configured devices" });
    }
    queueTelemetry(entry);
    return reply.code(202).send({ status: "queued" });
  });

  app.post("/telemetry/device/:configId/example", async (request, reply) => {
    syncRuntimeAuthFromFastifyRequest(runtime, request);
    const { configId } = request.params as { configId: string };
    const entry = registry.get(configId);
    if (!entry) {
      return reply.code(404).send({ ok: false, reason: `unknown config_id=${configId}` });
    }
    queueTelemetry(entry);
    return reply.code(202).send({ status: "queued" });
  });
}
