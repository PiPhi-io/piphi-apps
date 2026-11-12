import type { FastifyInstance } from "fastify";
import { dispatchAutomationActionFromFastify } from "piphi-runtime-kit-node/adapters/fastify";

import { commands } from "../contract.js";
import { automations } from "../state.js";

export function registerCommandRoutes(app: FastifyInstance): void {
  app.post("/command", async (request, reply) => {
    const body = (request.body ?? {}) as {
      contract_version?: string;
      command?: string;
      capability_id?: string;
      capability?: string;
      capability_requirements?: string[];
      config_id?: string;
      device_id?: string;
      entity_id?: string;
      target?: Record<string, unknown>;
      params?: Record<string, unknown>;
      args?: Record<string, unknown>;
    };
    const commandName = String(body.command ?? body.capability_id ?? "").trim();
    if (!commandName) {
      return reply.code(400).send({ ok: false, reason: "Missing command" });
    }
    if (!(commandName in commands)) {
      return reply.code(400).send({ ok: false, reason: `Unsupported command: ${commandName}` });
    }

    const target = body.target && typeof body.target === "object" ? body.target : {};
    const deviceId = String(body.device_id ?? target.device_id ?? "zwave-js-service");
    const configId = String(body.config_id ?? target.config_id ?? deviceId);
    const requestedCapabilities = [
      body.capability,
      ...(Array.isArray(body.capability_requirements) ? body.capability_requirements : []),
    ].filter((value): value is string => Boolean(value));
    const unsupportedCapability = requestedCapabilities.find((capability) => capability !== "device.refresh" && capability !== `action.${commandName}`);
    if (unsupportedCapability) {
      return reply.code(400).send({
        ok: false,
        error: "unsupported_capability",
        message: `This runtime does not support capability ${unsupportedCapability}`,
      });
    }
    const result = await dispatchAutomationActionFromFastify(automations, request, {
      ...body,
      command: commandName,
      args: body.params ?? body.args ?? {},
      deviceId,
      configId,
      target,
    });
    return reply.code(result.ok ? 200 : 422).send({
      ...result.toJSON(),
      ...(result.ok ? result.result : {}),
    });
  });
}
