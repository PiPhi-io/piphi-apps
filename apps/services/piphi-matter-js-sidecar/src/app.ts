import Fastify, { type FastifyInstance, type FastifyRequest } from "fastify";
import { networkInterfaces } from "node:os";
import {
  AutomationRegistry,
  FileAutomationIdempotencyStore,
} from "piphi-runtime-kit-node";
import { dispatchAutomationActionFromFastify } from "piphi-runtime-kit-node/adapters/fastify";

import { isSupportedCommand, supportedCommands } from "./capabilities.js";
import { registerSidecarAuthorization } from "./authorization.js";
import { checkBluezAdapter, type BlePreflightResult } from "./ble-preflight.js";
import { EventCursorExpiredError, MatterSidecarService } from "./service.js";
import type { JsonObject } from "./types.js";
import { publicErrorCode, redact } from "./redaction.js";

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

export function createApp(service: MatterSidecarService, options: {
  blePreflight?: () => Promise<BlePreflightResult>;
  bleBinding?: string;
  allowUnauthenticatedForTests?: boolean;
} = {}): FastifyInstance {
  const app = Fastify({
    logger: process.env.NODE_ENV !== "test" && process.env.NODE_TEST_CONTEXT === undefined,
    pluginTimeout: 60_000,
  });
  registerSidecarAuthorization(app, options.allowUnauthenticatedForTests);
  const automations = new AutomationRegistry({
    idempotencyStore: new FileAutomationIdempotencyStore(
      process.env.PIPHI_AUTOMATION_LEDGER_DIR ?? `${service.settings.storageDir}/automation-actions`,
    ),
  });

  for (const command of supportedCommands) {
    automations.action(command, { label: `Matter ${command.replaceAll("_", " ")}` })(async (request) => {
      if (command !== "refresh" && !service.settings.allowControl) throw statusError(403, "matter_control_disabled");
      const target = request.target && typeof request.target === "object" ? request.target as JsonObject : {};
      const nodeId = String(request.deviceId ?? target.node_id ?? "");
      const endpointId = Number(request.entityId ?? target.endpoint_id ?? 0);
      return service.invoke(nodeId, endpointId, command, request.args as JsonObject);
    });
  }

  app.addHook("onReady", async () => service.start());
  app.addHook("onClose", async () => service.stop());

  app.get("/health", async (_request, reply) => {
    const ok = service.backend.connected;
    return reply.code(ok ? 200 : 503).send(redact({ ok, ready: ok, dependencies: { matter_server: ok }, service: service.snapshot() }));
  });
  app.get("/v1/snapshot", async () => service.snapshot());
  app.get("/diagnostics", async () => redact({
    ok: service.backend.connected,
    diagnostics: service.snapshot(),
    security: {
      backend_bound_to_loopback: service.settings.backendHost === "127.0.0.1" || service.settings.backendHost === "::1",
      ble_enabled: service.settings.enableBle,
      credentials_exposed: false,
    },
  }));
  app.get("/v1/preflight", async () => {
    const interfaces = networkInterfaces();
    const selectedInterface = service.settings.primaryInterface;
    const selectedAddresses = selectedInterface ? interfaces[selectedInterface] : undefined;
    const interfacePresent = selectedInterface === undefined || selectedAddresses !== undefined;
    const externalIpv6 = Object.values(interfaces).some((addresses) => (
      addresses?.some((address) => !address.internal && address.family === "IPv6")
    ));
    const linkLocalIpv6 = Object.values(interfaces).some((addresses) => (
      addresses?.some((address) => !address.internal && address.family === "IPv6" && address.address.toLowerCase().startsWith("fe80:"))
    ));
    const backendDetails = service.backend.diagnostics();
    const server = backendDetails.server && typeof backendDetails.server === "object"
      ? backendDetails.server as JsonObject
      : {};
    let bleCheck: BlePreflightResult | { status: "disabled" } = { status: "disabled" };
    if (service.settings.enableBle) {
      bleCheck = (options.bleBinding ?? process.env.NOBLE_BINDINGS) === "dbus"
        ? await retryBlePreflight(options.blePreflight ?? checkBluezAdapter)
        : { status: "fail", adapter: "hci0", transport: "bluez_dbus", reason: "system_bus_unavailable" };
      if (bleCheck.status === "pass" && server.bluetooth_enabled !== true) {
        bleCheck = { status: "fail", adapter: "hci0", transport: "bluez_dbus", reason: "bluez_unavailable" };
      }
    }
    const readyForOnNetwork = service.backend.connected && interfacePresent && externalIpv6 && linkLocalIpv6;
    const checks = {
      backend_connected: { status: service.backend.connected ? "pass" : "fail" },
      selected_interface: {
        status: interfacePresent ? "pass" : "fail",
        mode: selectedInterface ? "explicit" : "automatic",
        ...(selectedInterface ? { name: selectedInterface } : {}),
      },
      external_ipv6: { status: externalIpv6 ? "pass" : "fail" },
      link_local_ipv6: { status: linkLocalIpv6 ? "pass" : "fail" },
      ble_commissioning: bleCheck,
      thread_commissioning: { status: "excluded" },
    };
    return {
      schema_version: "piphi.matter.preflight.v1",
      ready_for_on_network: readyForOnNetwork,
      ready_for_ble_wifi: readyForOnNetwork && bleCheck.status === "pass",
      checks,
      supported_scope: ["ethernet", "wifi_on_network"],
    };
  });

  app.get<{ Querystring: { node_id?: string } }>("/v1/devices/discover", async (request) => {
    return (await service.discover(request.query.node_id)).map(discoveryRecord);
  });
  app.get("/entities", async () => ({ entities: [] }));
  app.get<{ Querystring: { timeout_seconds?: string } }>("/v1/discovery/commissionables", async (request) => {
    const timeout = boundedTimeout(request.query.timeout_seconds);
    return (await service.discoverCommissionables(timeout)).map((record) => ({
      instance_name: record.instanceName ?? null,
      vendor_id: record.vendorId ?? null,
      product_id: record.productId ?? null,
      device_type: record.deviceType ?? null,
      long_discriminator: record.longDiscriminator ?? null,
      commissioning_mode: record.commissioningMode ?? null,
       address_count: record.addresses.length,
      metadata: {},
    }));
  });

  app.get("/v1/registry", async () => service.listRegistry());
  app.post("/v1/registry", async (_request, reply) => reply.code(410).send({
    ok: false,
    error: "registry_removed",
    message: "Matter.js owns commissioned-node inventory; use /v1/commission/code.",
  }));
  app.delete("/v1/registry/:nodeId/:endpointId", async (_request, reply) => {
    return reply.code(410).send({
      ok: false,
      error: "endpoint_shaped_decommission_removed",
      message: "Use POST /v1/nodes/:nodeId/decommission with explicit node confirmation.",
    });
  });
  app.post<{ Params: { nodeId: string }; Body: { confirm_node_id?: string } }>("/v1/nodes/:nodeId/decommission", async (request, reply) => {
    if (!service.settings.allowCommissioning) return reply.code(403).send({ ok: false, error: "matter_commissioning_disabled" });
    if (request.body?.confirm_node_id !== request.params.nodeId) {
      return reply.code(400).send({
        ok: false,
        error: "node_confirmation_required",
        message: "confirm_node_id must exactly match the node being decommissioned.",
      });
    }
    await service.removeNode(request.params.nodeId);
    return { removed: true, node_id: request.params.nodeId };
  });
  app.post<{ Body: { confirmation?: string } }>("/v1/admin/backup/quiesce", async (request, reply) => {
    if (request.body?.confirmation !== "quiesce-matter-controller") {
      return reply.code(400).send({ ok: false, error: "backup_quiesce_confirmation_required" });
    }
    return reply.code(202).send(await service.quiesceForBackup());
  });
  app.post("/v1/admin/backup/resume", async () => service.resumeAfterBackup());

  app.post<{ Body: { setup_payload?: string; network_only?: boolean } }>("/v1/commission/code", async (request, reply) => {
    if (!service.settings.allowCommissioning) return reply.code(403).send({ ok: false, error: "matter_commissioning_disabled" });
    const setupCode = request.body?.setup_payload ?? "";
    const endpoints = await service.commission(setupCode, request.body?.network_only ?? false);
    return reply.code(201).send({
      node_id: endpoints[0]?.nodeId ?? null,
      endpoints: endpoints.map(discoveryRecord),
    });
  });

  app.post<{ Body: { setup_payload?: string; ssid?: string; credentials?: string } }>("/v1/commission/wifi", async (request, reply) => {
    if (!service.settings.allowCommissioning) return reply.code(403).send({ ok: false, error: "matter_commissioning_disabled" });
    const endpoints = await service.provisionWifi(
      request.body?.setup_payload ?? "",
      request.body?.ssid ?? "",
      request.body?.credentials ?? "",
    );
    return reply.code(201).send({
      node_id: endpoints[0]?.nodeId ?? null,
      endpoints: endpoints.map(discoveryRecord),
    });
  });

  app.post<{ Body: { setup_payload?: string; operational_dataset?: string } }>("/v1/commission/thread", async (request, reply) => {
    void request;
    return reply.code(410).send({ ok: false, error: "thread_commissioning_out_of_scope" });
  });

  app.post("/v1/credentials/wifi", async (_request, reply) => reply.code(410).send({
    ok: false,
    error: "persistent_wifi_credentials_removed",
    message: "Use /v1/commission/wifi; PiPhi stores a unique temporary credential only for that operation.",
  }));
  app.delete("/v1/credentials/wifi", async (_request, reply) => {
    await service.backend.clearWifiCredentials();
    return reply.code(204).send();
  });
  app.post("/v1/credentials/thread", async (_request, reply) => reply.code(410).send({
    ok: false,
    error: "persistent_thread_dataset_removed",
    message: "Thread commissioning is outside this release; only defensive cleanup remains available.",
  }));
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
  app.get<{ Querystring: { after?: string } }>("/events", async (request, reply) => eventPage(service, request.query.after, reply));
  app.get<{ Querystring: { after?: string } }>("/v1/events", async (request, reply) => eventPage(service, request.query.after, reply));
  app.get("/v1/matter/snapshot", async () => service.transportSnapshot());
  app.get<{ Querystring: { after?: string; limit?: string } }>("/v1/matter/events", async (request, reply) => {
    const after = Number(request.query.after ?? 0);
    const limit = Number(request.query.limit ?? 100);
    if (!Number.isInteger(after) || after < 0 || !Number.isInteger(limit) || limit < 1 || limit > 500) {
      return reply.code(400).send({ ok: false, error: "after and limit must be bounded integers" });
    }
    return service.transportEvents(after, limit);
  });

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
    reply.code(statusCode).send({ ok: false, error: publicErrorCode(error) });
  });
  return app;
}

async function retryBlePreflight(check: () => Promise<BlePreflightResult>): Promise<BlePreflightResult> {
  let result = await check();
  for (let attempt = 1; attempt < 3 && result.status === "fail"; attempt += 1) {
    await new Promise((resolve) => setTimeout(resolve, 250));
    result = await check();
  }
  return result;
}

function eventPage(
  service: MatterSidecarService,
  after: string | undefined,
  reply: { code(statusCode: number): { send(payload: unknown): unknown } },
): JsonObject | unknown {
  try {
    return service.eventPage(after);
  } catch (error) {
    if (!(error instanceof EventCursorExpiredError)) throw error;
    return reply.code(409).send({
      ok: false,
      error: "event_cursor_expired",
      message: error.message,
      requested_cursor: error.cursor,
      oldest_cursor: error.oldestCursor ?? null,
      latest_cursor: error.latestCursor ?? null,
      dropped_event_count: error.droppedEventCount,
      recovery: "fetch_full_snapshot",
    });
  }
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

function statusError(statusCode: number, code: string): Error & { statusCode: number; code: string } {
  return Object.assign(new Error(code), { statusCode, code });
}
