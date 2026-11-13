import type { FastifyInstance } from "fastify";
import {
  buildDiscoveryResponse,
  normalizeDiscoveryInputs,
  type IntegrationDiscoveryRequest,
} from "piphi-runtime-kit-node";

import { configSchema } from "../contract.js";

export function registerDiscoveryRoutes(app: FastifyInstance): void {
  app.post("/discover", async (request) => {
    const body = (request.body ?? {}) as IntegrationDiscoveryRequest;
    const inputs = normalizeDiscoveryInputs(body.inputs);
    return buildDiscoveryResponse([
      {
        id: "zwave-js-service",
        deviceId: "zwave-js-service",
        host: "local-controller",
        alias: String(inputs.alias ?? "Z-Wave JS Controller"),
        metadata: { controller_path_required: true },
      },
    ]);
  });

  app.get("/ui-config", async () => {
    return configSchema;
  });
}
