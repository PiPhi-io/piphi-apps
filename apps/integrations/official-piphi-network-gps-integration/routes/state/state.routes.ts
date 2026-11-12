import express from "express";
import { RuntimeStateService } from "piphi-runtime-kit-node";

import { getStatePayload, refreshGPSDevice } from "../../lib/gps.js";
import { getRuntimeRegistry } from "../../lib/runtime.js";

export const router = express.Router();
const stateService = new RuntimeStateService(getRuntimeRegistry());
stateService.provide(async () => {
  const result = await refreshGPSDevice();
  if (!result.success) throw new Error(result.message ?? "GPS refresh failed");
}, { source: "GPS serial device" });

router.get("/state", async (req, res) => {
  const refresh = req.query.refresh === "true";
  if (!refresh) {
    res.json(getStatePayload());
    return;
  }
  const refreshRequestId = typeof req.query.refresh_request_id === "string"
    ? req.query.refresh_request_id
    : undefined;
  if (!refreshRequestId) {
    res.status(400).json({ detail: "refresh_request_id is required when refresh=true" });
    return;
  }
  res.json(await stateService.response({ refresh, refreshRequestId }));
});
