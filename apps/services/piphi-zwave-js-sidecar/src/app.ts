import Fastify from "fastify";

import { registerSidecarAuthorization } from "./authorization.js";
import { registerRoutes } from "./routes/index.js";
import { shutdownRuntime } from "./state.js";
import { restorePersistedConfig } from "./state.js";
import { publicErrorCode } from "./redaction.js";

export function createApp() {
  const app = Fastify({ logger: true });
  registerSidecarAuthorization(app);
  registerRoutes(app);
  app.addHook("onReady", async () => { await restorePersistedConfig(); });
  app.addHook("onClose", async () => shutdownRuntime());
  app.setErrorHandler((error, _request, reply) => {
    const status = Number(error && typeof error === "object" && "statusCode" in error ? error.statusCode : 500);
    reply.code(status >= 400 && status < 600 ? status : 500).send({ ok: false, error: publicErrorCode(error) });
  });
  return app;
}
