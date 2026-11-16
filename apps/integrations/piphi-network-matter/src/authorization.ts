import { timingSafeEqual } from "node:crypto";
import type { FastifyInstance } from "fastify";

export function registerCoreAuthorization(app: FastifyInstance): void {
  app.addHook("onRequest", async (request, reply) => {
    const path = request.url.split("?", 1)[0] ?? request.url;
    if (path === "/health") return;
    const expected = String(process.env.PIPHI_INTEGRATION_INTERNAL_TOKEN ?? "").trim();
    if (!expected) {
      if (process.env.NODE_ENV === "production") {
        return reply.code(503).send({ ok: false, error: "core_authorization_not_configured" });
      }
      return;
    }
    const [scheme = "", bearerCredential = ""] = String(request.headers.authorization ?? "").split(" ", 2);
    const runtimeCredential = String(request.headers["x-piphi-integration-token"] ?? "").trim();
    const credential = runtimeCredential || (scheme.toLowerCase() === "bearer" ? bearerCredential : "");
    if (!constantTimeEqual(credential, expected)) {
      return reply.code(401).send({ ok: false, error: "core_authorization_failed" });
    }
  });
}

function constantTimeEqual(left: string, right: string): boolean {
  const leftBuffer = Buffer.from(left);
  const rightBuffer = Buffer.from(right);
  return leftBuffer.length === rightBuffer.length && timingSafeEqual(leftBuffer, rightBuffer);
}
