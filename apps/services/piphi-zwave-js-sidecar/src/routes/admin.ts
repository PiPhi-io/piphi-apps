import type { FastifyInstance } from "fastify";

import {
  beginCommissioning,
  beginExclusion,
  cancelCommissioning,
  cancelExclusion,
  createNVMBackup,
  reconcileFailedNode,
  restoreNVMBackup,
} from "../state.js";

export function registerAdminRoutes(app: FastifyInstance): void {
  app.post<{ Body: { confirmation?: string; dsk?: string; security_classes?: string[]; timeout_seconds?: number } }>("/v1/admin/inclusion/start", async (request, reply) => {
    if (request.body?.confirmation !== "start-secure-inclusion") return reply.code(400).send({ ok: false, error: "inclusion_confirmation_required" });
    const timeout = boundedTimeout(request.body.timeout_seconds);
    return reply.code(202).send(await beginCommissioning({ dsk: request.body.dsk ?? "", security_classes: request.body.security_classes ?? [], timeout_seconds: timeout }));
  });
  app.post("/v1/admin/inclusion/stop", async () => cancelCommissioning());
  app.post<{ Body: { confirmation?: string; timeout_seconds?: number } }>("/v1/admin/exclusion/start", async (request, reply) => {
    if (request.body?.confirmation !== "start-exclusion") return reply.code(400).send({ ok: false, error: "exclusion_confirmation_required" });
    return reply.code(202).send(await beginExclusion(boundedTimeout(request.body.timeout_seconds)));
  });
  app.post("/v1/admin/exclusion/stop", async () => cancelExclusion());
  app.post<{ Params: { nodeId: string }; Body: { confirmation?: string } }>("/v1/admin/nodes/:nodeId/remove-failed", async (request, reply) => {
    const nodeId = boundedNodeId(request.params.nodeId);
    if (request.body?.confirmation !== `remove-failed:${nodeId}`) return reply.code(400).send({ ok: false, error: "remove_failed_confirmation_required" });
    return reconcileFailedNode("remove", nodeId);
  });
  app.post<{ Params: { nodeId: string }; Body: { confirmation?: string; dsk?: string; security_classes?: string[] } }>("/v1/admin/nodes/:nodeId/replace-failed", async (request, reply) => {
    const nodeId = boundedNodeId(request.params.nodeId);
    if (request.body?.confirmation !== `replace-failed:${nodeId}`) return reply.code(400).send({ ok: false, error: "replace_failed_confirmation_required" });
    return reply.code(202).send(await reconcileFailedNode("replace", nodeId, { dsk: request.body.dsk ?? "", security_classes: request.body.security_classes ?? [] }));
  });
  app.post<{ Body: { confirmation?: string } }>("/v1/admin/nvm/backups", async (request, reply) => {
    if (request.body?.confirmation !== "backup-controller-nvm") return reply.code(400).send({ ok: false, error: "nvm_backup_confirmation_required" });
    return reply.code(201).send(await createNVMBackup());
  });
  app.post<{ Params: { backupId: string }; Body: { confirmation?: string } }>("/v1/admin/nvm/backups/:backupId/restore", async (request, reply) => {
    if (!/^[a-zA-Z0-9-]{1,100}$/.test(request.params.backupId)) return reply.code(400).send({ ok: false, error: "backup_id_invalid" });
    return reply.code(202).send(await restoreNVMBackup(request.params.backupId, request.body?.confirmation ?? ""));
  });
}

function boundedTimeout(value: unknown): number {
  const parsed = Number(value ?? 60);
  if (!Number.isInteger(parsed) || parsed < 15 || parsed > 300) throw new Error("administration_timeout_invalid");
  return parsed;
}

function boundedNodeId(value: string): number {
  const parsed = Number(value);
  if (!Number.isInteger(parsed) || parsed < 1 || parsed > 4_000) throw new Error("node_id_invalid");
  return parsed;
}
