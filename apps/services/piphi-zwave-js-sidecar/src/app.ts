import Fastify from "fastify";

import { registerRoutes } from "./routes/index.js";
import { shutdownRuntime } from "./state.js";

export function createApp() {
  const app = Fastify({ logger: true });
  registerRoutes(app);
  app.addHook("onClose", async () => shutdownRuntime());
  return app;
}
