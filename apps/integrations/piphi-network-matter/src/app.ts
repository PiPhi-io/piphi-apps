import Fastify, { type FastifyInstance } from "fastify";
import { isCommand } from "./capabilities.js";
import { registerCoreAuthorization } from "./authorization.js";
import type { ConfigStore } from "./config-store.js";
import type { Reconciler } from "./reconciler.js";
import { SidecarRequestError, type SidecarClient } from "./sidecar-client.js";
import { publicErrorCode, redact } from "./redaction.js";
import type { JsonObject } from "./types.js";

interface ConfigBody { node_id?: string; endpoint_id?: number; alias?: string; enabled?: boolean }
interface CommandBody { command?: string; node_id?: string; endpoint_id?: number; entity_id?: string }
interface CommissionBody { setup_payload?: string; network_only?: boolean }
interface WifiCommissionBody { setup_payload?: string; ssid?: string; credentials?: string }

export function createApp(reconciler: Reconciler, sidecar: SidecarClient, configs: ConfigStore, options: {
  allowUnauthenticatedForTests?: boolean;
  allowMutations?: boolean;
} = {}): FastifyInstance {
  const app = Fastify({ logger: process.env.NODE_ENV !== "test" && process.env.NODE_TEST_CONTEXT === undefined });
  registerCoreAuthorization(app, options.allowUnauthenticatedForTests);

  app.addHook("onReady", async () => reconciler.start());
  app.addHook("onClose", async () => reconciler.stop());
  app.get("/health", async (_request, reply) => {
    const status = reconciler.status();
    const ok = status.connected && status.stream_id !== null;
    return reply.code(ok ? 200 : 503).send(redact({ ok, ready: ok, dependencies: { matter_sidecar: status.connected }, reconciliation: status }));
  });
  app.get("/entities", async () => ({ entities: reconciler.entities() }));
  app.get("/state", async () => ({ sampled_at: new Date().toISOString(), entities: reconciler.entities().map(({ id, device_id, state }) => ({ id, device_id, state })) }));
  app.post("/telemetry", async () => ({ results: await reconciler.deliverTelemetry() }));
  app.get("/events", async () => ({ cursor: reconciler.status().cursor, contract: "Cursor loss triggers a full authenticated sidecar snapshot before streaming resumes." }));
  app.get("/diagnostics", async () => ({
    schema_version: "piphi.matter.parent.diagnostics.v1",
    reconciliation: reconciler.status(),
    configured_endpoint_count: configs.list().length,
    entities: reconciler.entities().map((entity) => ({
      id: entity.id,
      device_id: entity.device_id,
      connected: entity.state.connected,
      capabilities: entity.capabilities,
      available_commands: entity.available_commands,
    })),
    transport: {
      authenticated: true,
      snapshot_schema: "piphi.matter.snapshot.v1",
      events_schema: "piphi.matter.events.v1",
    },
    supported_scope: {
      transports: ["ethernet", "wifi_on_network"],
      device_features: ["on_off"],
      experimental: ["ble"],
      excluded: ["thread"],
    },
  }));
  app.get("/repairs", async () => {
    const status = reconciler.status();
    const issues = [];
    if (!status.connected) {
      issues.push({
        id: "matter_sidecar_unavailable",
        severity: "error",
        summary: "The managed Matter controller is unavailable.",
        action: "Check the sidecar health, authentication token, and host-network listener before retrying.",
      });
    } else if (!status.stream_id) {
      issues.push({
        id: "matter_event_stream_not_initialized",
        severity: "warning",
        summary: "Matter state has not completed its first snapshot reconciliation.",
        action: "Wait for reconciliation or restart the parent integration if this persists.",
      });
    }
    if (status.delivery_error) {
      issues.push({
        id: "matter_core_delivery_failed",
        severity: "warning",
        summary: "Matter state is reconciled locally but delivery to PiPhi Core failed.",
        action: "Check Core availability and the runtime container/token credentials; device control can remain available.",
      });
    }
    return { schema_version: "piphi.matter.repairs.v1", issues };
  });
  app.get("/preflight", async () => redact(await sidecar.preflight()));
  app.post<{ Body: { confirmation?: string } }>("/backup/quiesce", async (request, reply) => {
    if (request.body?.confirmation !== "quiesce-matter-controller") {
      return reply.code(400).send({ ok: false, error: "backup_quiesce_confirmation_required" });
    }
    return reply.code(202).send(await sidecar.quiesceForBackup());
  });
  app.post("/backup/resume", async () => {
    const result = await sidecar.resumeAfterBackup();
    await reconciler.fullSnapshot();
    return result;
  });
  app.get<{ Querystring: { timeout_seconds?: string } }>("/commissioning/commissionables", async (request, reply) => {
    const timeoutSeconds = Number(request.query.timeout_seconds ?? 10);
    if (!Number.isInteger(timeoutSeconds) || timeoutSeconds < 1 || timeoutSeconds > 60) {
      return reply.code(400).send({ ok: false, error: "timeout_seconds_must_be_between_1_and_60" });
    }
    return { commissionables: redact(await sidecar.commissionables(timeoutSeconds)) };
  });
  app.post<{ Body: CommissionBody }>("/commissioning/code", async (request, reply) => {
    const setupPayload = request.body?.setup_payload?.trim() ?? "";
    if (!setupPayload) return reply.code(400).send({ ok: false, error: "setup_payload_required" });
    if (request.body?.network_only !== true) {
      return reply.code(400).send({
        ok: false,
        error: "network_only_required",
        message: "This release supports only Matter devices already reachable on Ethernet or Wi-Fi.",
      });
    }
    const result = await sidecar.commissionOnNetwork(setupPayload);
    await reconciler.fullSnapshot();
    return reply.code(201).send({
      ok: true,
      node_id: result.node_id ?? null,
      reconciled_entity_count: reconciler.entities().length,
    });
  });
  app.post<{ Body: WifiCommissionBody }>("/commissioning/wifi", async (request, reply) => {
    const setupPayload = request.body?.setup_payload?.trim() ?? "";
    const ssid = request.body?.ssid ?? "";
    const credentials = request.body?.credentials ?? "";
    if (!setupPayload) return reply.code(400).send({ ok: false, error: "setup_payload_required" });
    if (!ssid || !credentials) {
      return reply.code(400).send({ ok: false, error: "wifi_credentials_required" });
    }
    const preflight = await sidecar.preflight();
    if (preflight.ready_for_ble_wifi !== true) {
      return reply.code(503).send({ ok: false, error: "matter_ble_wifi_unavailable" });
    }
    const result = await sidecar.provisionWifi(setupPayload, ssid, credentials);
    await reconciler.fullSnapshot();
    return reply.code(201).send({
      ok: true,
      node_id: result.node_id ?? null,
      reconciled_entity_count: reconciler.entities().length,
    });
  });
  app.post("/commissioning/thread", async (request, reply) => {
    void request;
    return reply.code(410).send({ ok: false, error: "thread_commissioning_out_of_scope" });
  });
  app.post<{ Params: { nodeId: string }; Body: { confirm_node_id?: string } }>("/nodes/:nodeId/decommission", async (request, reply) => {
    if (request.body?.confirm_node_id !== request.params.nodeId) {
      return reply.code(400).send({ ok: false, error: "node_confirmation_required" });
    }
    const controllerIdentityHash = reconciler.entities().find((entity) => (
      entity.metadata.node_id === request.params.nodeId
    ))?.metadata.controller_identity_hash;
    const previousConfigs = configs.list();
    const removed_config_count = await configs.removeNode(request.params.nodeId, controllerIdentityHash);
    let result: JsonObject;
    try {
      result = await sidecar.decommissionNode(request.params.nodeId);
    } catch (error) {
      await configs.replaceAll(previousConfigs);
      throw error;
    }
    await reconciler.fullSnapshot();
    return { ok: true, node_id: request.params.nodeId, removed_config_count, result };
  });
  app.get("/config", async () => ({ endpoints: configs.list(), sidecar: { configured: true, authenticated: true } }));
  app.post<{ Body: ConfigBody }>("/config", async (request, reply) => {
    const nodeId = String(request.body?.node_id ?? "");
    const endpointId = Number(request.body?.endpoint_id);
    if (!nodeId || !Number.isInteger(endpointId)) return reply.code(400).send({ ok: false, error: "node_id and endpoint_id are required" });
    const target = reconciler.entities().find((entity) => (
      entity.metadata.node_id === nodeId && entity.metadata.endpoint_id === endpointId
    ));
    if (!target) return reply.code(404).send({ ok: false, error: "matter_endpoint_not_found" });
    const previous = configs.get(target.metadata.controller_identity_hash, nodeId, endpointId);
    const item = await configs.set({
      controller_identity_hash: target.metadata.controller_identity_hash,
      node_id: nodeId,
      endpoint_id: endpointId,
      enabled: request.body.enabled ?? true,
      ...(request.body.alias ? { alias: request.body.alias } : {}),
    });
    try {
      await reconciler.fullSnapshot();
    } catch (error) {
      if (previous) await configs.set(previous);
      else await configs.delete(target.metadata.controller_identity_hash, nodeId, endpointId);
      throw error;
    }
    return item;
  });
  app.post<{ Body: CommandBody }>("/command", async (request, reply) => {
    const command = String(request.body?.command ?? "");
    if (!isCommand(command)) return reply.code(400).send({ ok: false, error: "unsupported_command" });
    const target = resolveTarget(request.body, reconciler);
    if (!target) return reply.code(404).send({ ok: false, error: "entity_not_found" });
    if (!target.available_commands.includes(command)) return reply.code(422).send({ ok: false, error: "command_not_negotiated" });
    if (command !== "refresh" && options.allowMutations !== true) {
      return reply.code(403).send({ ok: false, error: "matter_control_disabled" });
    }
    const idempotencyKey = String(request.headers["x-piphi-idempotency-key"] ?? "").trim();
    if (command === "toggle" && !idempotencyKey) {
      return reply.code(400).send({ ok: false, error: "idempotency_key_required" });
    }
    const result = await sidecar.command(target.metadata.node_id, target.metadata.endpoint_id, command, idempotencyKey || undefined);
    await reconciler.fullSnapshot();
    return { ok: true, entity_id: target.id, command, result };
  });
  app.setErrorHandler((error, _request, reply) => {
    if (error instanceof SidecarRequestError) {
      const classified = classifySidecarError(error.status, error.code);
      return reply.code(classified.status).send({ ok: false, error: classified.code });
    }
    return reply.code(502).send({ ok: false, error: publicErrorCode(error) });
  });
  return app;
}

function classifySidecarError(status: number, code?: string): { status: 403 | 404 | 409 | 422 | 502 | 503; code: string } {
  if (status === 403 && ["matter_control_disabled", "matter_commissioning_disabled"].includes(code ?? "")) {
    return { status: 403, code: code! };
  }
  if (status === 400 || status === 422) return { status: 422, code: "matter_operation_rejected" };
  if (status === 404) return { status: 404, code: "matter_resource_not_found" };
  if (status === 409) return { status: 409, code: "matter_operation_conflict" };
  if (status === 503) return { status: 503, code: "matter_sidecar_unavailable" };
  if (status === 401 || status === 403) return { status: 502, code: "matter_sidecar_authentication_failed" };
  return { status: 502, code: "matter_sidecar_request_failed" };
}

function resolveTarget(body: CommandBody, reconciler: Reconciler) {
  if (body.entity_id) return reconciler.entities().find((entity) => entity.id === body.entity_id);
  if (!body.node_id || !Number.isInteger(body.endpoint_id)) return undefined;
  return reconciler.entities().find((entity) => (
    entity.metadata.node_id === body.node_id && entity.metadata.endpoint_id === Number(body.endpoint_id)
  ));
}
