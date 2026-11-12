import Fastify from "fastify";

import { registerRoutes } from "./routes/index.js";

export function createApp() {
  const app = Fastify({ logger: true });
  registerRoutes(app);
  return app;
}
