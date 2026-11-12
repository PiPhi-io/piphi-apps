import type { FastifyInstance } from "fastify";

import { capabilities, commands, fallbackEntity } from "../contract.js";
import { registry } from "../state.js";
import type { DeviceEntry } from "../types.js";

export function registerEntityRoutes(app: FastifyInstance): void {
  app.get("/entities", async () => {
    const entries = [...registry.entries.values()] as DeviceEntry[];
    return {
      entities: entries.length > 0
        ? entries.map((entry) => ({
            id: entry.deviceId,
            name: entry.alias ?? "Demo Device",
            config_id: entry.configId,
            device_id: entry.deviceId,
            entity_type: fallbackEntity.entity_type,
            capabilities: fallbackEntity.capabilities,
            available_commands: fallbackEntity.available_commands,
            dashboard: fallbackEntity.dashboard,
          }))
        : [fallbackEntity],
      capabilities,
      commands,
    };
  });
}
