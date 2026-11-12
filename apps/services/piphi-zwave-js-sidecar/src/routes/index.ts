import type { FastifyInstance } from "fastify";

import { registerCommandRoutes } from "./commands.js";
import { registerConfigRoutes } from "./config.js";
import { registerDiscoveryRoutes } from "./discovery.js";
import { registerEntityRoutes } from "./entities.js";
import { registerEventRoutes } from "./events.js";
import { registerHealthRoutes } from "./health.js";
import { registerRuntimeRoutes } from "./runtime.js";
import { registerTelemetryRoutes } from "./telemetry.js";

export function registerRoutes(app: FastifyInstance): void {
  registerHealthRoutes(app);
  registerDiscoveryRoutes(app);
  registerConfigRoutes(app);
  registerRuntimeRoutes(app);
  registerEntityRoutes(app);
  registerEventRoutes(app);
  registerTelemetryRoutes(app);
  registerCommandRoutes(app);
}
