import type { FastifyInstance } from "fastify";

import { endpoints, requiredEndpoints } from "../contract.js";
import { projectKind } from "../settings.js";
import { controllerDiagnostics, registry, starter } from "../state.js";

export function registerHealthRoutes(app: FastifyInstance): void {
  app.get("/health", async () => {
    const diagnostics = controllerDiagnostics();
    const ready = registry.ids().length === 0 || (diagnostics.snapshot as { lifecycle?: string } | null)?.lifecycle === "ready";
    return {
      ...starter.healthResponse({}),
      ready,
      dependencies: { controller: ready },
    };
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
