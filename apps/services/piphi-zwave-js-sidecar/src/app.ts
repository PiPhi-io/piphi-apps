import Fastify from "fastify";

import { registerSidecarAuthorization } from "./authorization.js";
import { registerRoutes } from "./routes/index.js";
import { shutdownRuntime } from "./state.js";

export function createApp() {
  const app = Fastify({ logger: true });
  registerSidecarAuthorization(app);
  registerRoutes(app);
  app.addHook("onClose", async () => shutdownRuntime());
  return app;
}
