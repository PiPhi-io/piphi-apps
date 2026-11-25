import { timingSafeEqual } from "node:crypto";

import type { FastifyInstance } from "fastify";

const PUBLIC_PATHS = new Set(["/health"]);

export function registerSidecarAuthorization(app: FastifyInstance, allowUnauthenticatedForTests = false): void {
  app.addHook("onRequest", async (request, reply) => {
    const path = request.url.split("?", 1)[0] ?? request.url;
    if (PUBLIC_PATHS.has(path)) return;

    const expected = sidecarToken();
    if (!expected && allowUnauthenticatedForTests && process.env.NODE_ENV === "test") return;
    if (!expected) return reply.code(503).send({ ok: false, error: "sidecar_authorization_not_configured" });

    const authorization = String(request.headers.authorization ?? "");
    const [scheme = "", credential = ""] = authorization.split(" ", 2);
    if (scheme.toLowerCase() !== "bearer" || !constantTimeEqual(credential, expected)) {
      return reply.code(401).send({ ok: false, error: "sidecar_authorization_failed" });
    }
  });
}

function sidecarToken(): string {
  return String(
    process.env.PIPHI_MATTER_SIDECAR_TOKEN
    ?? process.env.PIPHI_INTEGRATION_INTERNAL_TOKEN
    ?? "",
  ).trim();
}

function constantTimeEqual(left: string, right: string): boolean {
  const leftBuffer = Buffer.from(left);
  const rightBuffer = Buffer.from(right);
  if (leftBuffer.length !== rightBuffer.length) return false;
  return timingSafeEqual(leftBuffer, rightBuffer);
}
