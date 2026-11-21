import crypto from "node:crypto";
import type { NextFunction, Request, Response } from "express";

function enabled(value: string | undefined): boolean {
  return ["1", "true", "yes", "on"].includes(String(value ?? "").trim().toLowerCase());
}

export function requireRuntimeAuth(req: Request, res: Response, next: NextFunction): void {
  if (req.path === "/health" || req.path === "/health/") {
    next();
    return;
  }

  const expected = String(process.env.PIPHI_INTEGRATION_INTERNAL_TOKEN ?? "").trim();
  if (!expected) {
    if (enabled(process.env.PIPHI_ALLOW_UNAUTHENTICATED)) {
      next();
      return;
    }
    res.status(503).json({ error: "runtime authentication is not configured" });
    return;
  }

  const supplied = String(req.header("X-PiPhi-Integration-Token") ?? "");
  const valid =
    supplied.length === expected.length &&
    crypto.timingSafeEqual(Buffer.from(supplied), Buffer.from(expected));
  if (!valid) {
    res.status(401).json({ error: "invalid runtime token" });
    return;
  }
  next();
}
