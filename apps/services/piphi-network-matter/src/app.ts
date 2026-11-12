import Fastify, { type FastifyInstance, type FastifyRequest } from "fastify";
import {
  AutomationRegistry,
  FileAutomationIdempotencyStore,
} from "piphi-runtime-kit-node";
import { dispatchAutomationActionFromFastify } from "piphi-runtime-kit-node/adapters/fastify";

import { isSupportedCommand, supportedCommands } from "./capabilities.js";
import { MatterSidecarService } from "./service.js";
import type { JsonObject } from "./types.js";

interface CommandBody {
  node_id?: string;
  endpoint_id?: number;
  command?: string;
  args?: JsonObject;
  params?: JsonObject;
  device_id?: string;
  entity_id?: string;
  config_id?: string;
  target?: JsonObject;
}

export function createApp(service: MatterSidecarService): FastifyInstance {
  const app = Fastify({ logger: process.env.NODE_ENV !== "test" && process.env.NODE_TEST_CONTEXT === undefined });
  const automations = new AutomationRegistry({
    idempotencyStore: new FileAutomationIdempotencyStore(
      process.env.PIPHI_AUTOMATION_LEDGER_DIR ?? `${service.settings.storageDir}/automation-actions`,
    ),
  });

  for (const command of supportedCommands) {
    automations.action(command, { label: `Matter ${command.replaceAll("_", " ")}` })(async (request) => {
      const target = request.target && typeof request.target === "object" ? request.target as JsonObject : {};
      const nodeId = String(request.deviceId ?? target.node_id ?? "");
      const endpointId = Number(request.entityId ?? target.endpoint_id ?? 0);
      return service.invoke(nodeId, endpointId, command, request.args as JsonObject);
    });
  }

  app.addHook("onReady", async () => service.start());
  app.addHook("onClose", async () => service.stop());

  app.get("/health", async () => ({ ok: service.backend.connected, service: service.snapshot() }));
  app.get("/v1/snapshot", async () => service.snapshot());
  app.get("/diagnostics", async () => ({
    ok: service.backend.connected,
    diagnostics: service.snapshot(),
    security: {
      backend_bound_to_loopback: service.settings.backendHost === "127.0.0.1" || service.settings.backendHost === "::1",
      ble_enabled: service.settings.enableBle,
      credentials_exposed: false,
    },
  }));

  app.get<{ Querystring: { node_id?: string } }>("/v1/devices/discover", async (request) => {
    return (await service.discover(request.query.node_id)).map(discoveryRecord);
  });
  app.get("/entities", async () => service.entities());
  app.get<{ Querystring: { timeout_seconds?: string } }>("/v1/discovery/commissionables", async (request) => {
    const timeout = boundedTimeout(request.query.timeout_seconds);
    return (await service.discoverCommissionables(timeout)).map((record) => ({
      instance_name: record.instanceName ?? null,
      vendor_id: record.vendorId ?? null,
      product_id: record.productId ?? null,
      device_type: record.deviceType ?? null,
      long_discriminator: record.longDiscriminator ?? null,
      commissioning_mode: record.commissioningMode ?? null,
      addresses: record.addresses,
      metadata: {},
    }));
  });

  app.get("/v1/registry", async () => service.listRegistry());
  app.post("/v1/registry", async (_request, reply) => reply.code(410).send({
    ok: false,
    error: "registry_removed",
    message: "Matter.js owns commissioned-node inventory; use /v1/commission/code.",
  }));
  app.delete<{ Params: { nodeId: string; endpointId: string } }>("/v1/registry/:nodeId/:endpointId", async (request) => {
    await service.removeNode(request.params.nodeId);
    return { removed: true, node_id: request.params.nodeId, endpoint_id: Number(request.params.endpointId) };
  });

  app.post<{ Body: { setup_payload?: string; network_only?: boolean } }>("/v1/commission/code", async (request, reply) => {
    const setupCode = request.body?.setup_payload ?? "";
    const endpoints = await service.commission(setupCode, request.body?.network_only ?? false);
    return reply.code(201).send({
      node_id: endpoints[0]?.nodeId ?? null,
      endpoints: endpoints.map(discoveryRecord),
    });
  });

  app.post<{ Body: { ssid?: string; credentials?: string } }>("/v1/credentials/wifi", async (request, reply) => {
    const ssid = request.body?.ssid?.trim();
    const credentials = request.body?.credentials;
    if (!ssid || !credentials) return reply.code(400).send({ ok: false, error: "ssid and credentials are required" });
    await service.backend.setWifiCredentials(ssid, credentials);
    return reply.code(204).send();
  });
  app.delete("/v1/credentials/wifi", async (_request, reply) => {
    await service.backend.clearWifiCredentials();
    return reply.code(204).send();
  });
  app.post<{ Body: { operational_dataset?: string } }>("/v1/credentials/thread", async (request, reply) => {
    const dataset = request.body?.operational_dataset?.trim();
    if (!dataset) return reply.code(400).send({ ok: false, error: "operational_dataset is required" });
    await service.backend.setThreadDataset(dataset);
    return reply.code(204).send();
  });
  app.delete("/v1/credentials/thread", async (_request, reply) => {
    await service.backend.clearThreadDataset();
    return reply.code(204).send();
  });

  app.get("/v1/configs", async () => service.listConfigs());
  app.post<{ Body: { node_id?: string; endpoint_id?: number; alias?: string } }>("/v1/configs", async (request, reply) => {
    const nodeId = String(request.body?.node_id ?? "");
    const endpointId = Number(request.body?.endpoint_id);
    if (!nodeId || !Number.isInteger(endpointId)) return reply.code(400).send({ ok: false, error: "node_id and endpoint_id are required" });
    return reply.code(201).send(await service.configure(nodeId, endpointId, request.body?.alias));
  });
  app.delete<{ Params: { nodeId: string; endpointId: string } }>("/v1/configs/:nodeId/:endpointId", async (request, reply) => {
    const removed = await service.removeConfig(request.params.nodeId, Number(request.params.endpointId));
    if (!removed) return reply.code(404).send({ ok: false, error: "configured endpoint not found" });
    return { removed: true, node_id: request.params.nodeId, endpoint_id: Number(request.params.endpointId) };
  });

  app.post("/v1/telemetry/poll", async () => service.telemetry());
  app.get<{ Querystring: { after?: string } }>("/events", async (request) => ({ events: service.events(request.query.after) }));
  app.get<{ Querystring: { after?: string } }>("/v1/events", async (request) => ({ events: service.events(request.query.after) }));

  app.post<{ Body: CommandBody }>("/v1/commands/invoke", async (request, reply) => {
    return dispatchCommand(automations, request, reply, request.body);
  });
  app.post<{ Body: CommandBody }>("/command", async (request, reply) => {
    return dispatchCommand(automations, request, reply, request.body);
  });

  app.setErrorHandler((error, _request, reply) => {
    const candidate = error && typeof error === "object" && "statusCode" in error
      ? Number(error.statusCode)
      : 400;
    const statusCode = Number.isInteger(candidate) && candidate >= 400 ? candidate : 400;
    const message = error instanceof Error ? error.message : String(error);
    reply.code(statusCode).send({ ok: false, error: message });
  });
  return app;
}

async function dispatchCommand(
  automations: AutomationRegistry,
  request: FastifyRequest,
  reply: { code(statusCode: number): { send(payload: unknown): unknown } },
  body: CommandBody,
) {
  const command = String(body?.command ?? "");
  if (!isSupportedCommand(command)) return reply.code(400).send({ ok: false, error: `Unsupported command: ${command}` });
  const target = body.target && typeof body.target === "object" ? body.target : {};
  const nodeId = String(body.node_id ?? body.device_id ?? target.node_id ?? "");
  const endpointId = Number(body.endpoint_id ?? body.entity_id ?? target.endpoint_id ?? 0);
  if (!nodeId || !Number.isInteger(endpointId)) return reply.code(400).send({ ok: false, error: "node_id and endpoint_id are required" });
  const result = await dispatchAutomationActionFromFastify(automations, request, {
    ...body,
    command,
    args: body.args ?? body.params ?? {},
    deviceId: nodeId,
    entityId: String(endpointId),
    configId: body.config_id ?? `${nodeId}:${endpointId}`,
    target: { ...target, node_id: nodeId, endpoint_id: endpointId },
  });
  return reply.code(result.ok ? 200 : 422).send({
    ...result.toJSON(),
    ...(result.ok ? result.result : {}),
  });
}

function discoveryRecord(endpoint: Awaited<ReturnType<MatterSidecarService["discover"]>>[number]) {
  const id = `${endpoint.nodeId}:${endpoint.endpointId}`;
  return {
    id,
    device_id: id,
    node_id: endpoint.nodeId,
    endpoint_id: endpoint.endpointId,
    name: endpoint.name,
    vendor_name: endpoint.vendorName ?? null,
    product_name: endpoint.productName ?? null,
    device_types: endpoint.deviceTypes,
    capabilities: endpoint.capabilities,
    command_bindings: endpoint.commandBindings,
    metadata: endpoint.metadata,
  };
}

function boundedTimeout(value: string | undefined): number {
  const parsed = Number(value ?? 5);
  return Number.isInteger(parsed) && parsed >= 1 && parsed <= 60 ? parsed : 5;
}
