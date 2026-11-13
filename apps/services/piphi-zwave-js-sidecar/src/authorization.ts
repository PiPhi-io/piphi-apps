import { timingSafeEqual } from "node:crypto";

import type { FastifyInstance } from "fastify";

const PROTECTED_PATHS = ["/command", "/v1/zwave/"];

export function registerSidecarAuthorization(app: FastifyInstance): void {
  app.addHook("onRequest", async (request, reply) => {
    const path = request.url.split("?", 1)[0] ?? request.url;
    if (!PROTECTED_PATHS.some((prefix) => path === prefix || path.startsWith(prefix))) return;

    const expected = String(
      process.env.PIPHI_ZWAVE_SIDECAR_TOKEN
      ?? process.env.PIPHI_INTEGRATION_INTERNAL_TOKEN
      ?? "",
    ).trim();
    if (!expected) {
      if (process.env.NODE_ENV === "production") {
        return reply.code(503).send({ ok: false, reason: "sidecar_authorization_not_configured" });
      }
      return;
    }
    const authorization = String(request.headers.authorization ?? "");
    const [scheme, credential = ""] = authorization.split(" ", 2);
    if (scheme.toLowerCase() !== "bearer" || !constantTimeEqual(credential, expected)) {
      return reply.code(401).send({ ok: false, reason: "sidecar_authorization_failed" });
    }
  });
}

function constantTimeEqual(left: string, right: string): boolean {
  const leftBuffer = Buffer.from(left);
  const rightBuffer = Buffer.from(right);
  if (leftBuffer.length !== rightBuffer.length) return false;
  return timingSafeEqual(leftBuffer, rightBuffer);
}
