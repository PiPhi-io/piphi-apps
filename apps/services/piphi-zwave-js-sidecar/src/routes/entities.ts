import type { FastifyInstance } from "fastify";

import { capabilities, commands } from "../contract.js";

export function registerEntityRoutes(app: FastifyInstance): void {
  app.get("/entities", async () => {
    return {
      entities: [],
      capabilities,
      commands,
    };
  });
}
