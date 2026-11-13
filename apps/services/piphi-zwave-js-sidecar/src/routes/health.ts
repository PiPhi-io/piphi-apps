import type { FastifyInstance } from "fastify";

import { endpoints, requiredEndpoints } from "../contract.js";
import { projectKind } from "../settings.js";
import { controllerDiagnostics, registry, starter } from "../state.js";

export function registerHealthRoutes(app: FastifyInstance): void {
  app.get("/health", async () => {
    return starter.healthResponse({
      activeConfigs: registry.ids().length,
      controller: controllerDiagnostics(),
    });
  });

  app.get("/diagnostics", async () => {
    return starter.diagnosticsResponse({
      activeConfigIds: registry.ids(),
      recentEventCount: registry.recentEvents.length,
      kind: projectKind,
      contract: {
        endpoints,
        required: requiredEndpoints,
      },
      controller: controllerDiagnostics(),
    });
  });
}
