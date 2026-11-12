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
        host: String(inputs.host ?? "127.0.0.1"),
        alias: "Z-Wave JS Service",
      },
    ]);
  });

  app.get("/ui-config", async () => {
    return configSchema;
  });
}
