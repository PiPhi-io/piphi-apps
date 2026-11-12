import express from "express";
import { buildConfigRemoveResponse } from "piphi-runtime-kit-node";

import { deconfigureGPSDevice } from "../../lib/gps.js";

export const router = express.Router();

router.post("/deconfigure", async (req, res) => {
  const payload = (req.body ?? {}) as { id?: string; config?: { id?: string; path?: string } };
  const result = await deconfigureGPSDevice(payload);
  res.json({
    ...buildConfigRemoveResponse({
      configId: String(payload.id ?? payload.config?.id ?? payload.config?.path ?? "gps-device"),
      removed: Boolean(result.removed),
    }),
    removed_count: result.removed ?? 0,
  });
});
