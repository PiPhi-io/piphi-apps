import express from "express";
import { buildRuntimeHealthResponse } from "piphi-runtime-kit-node";

import { getHealthSummary, getRuntimeContext } from "../../lib/runtime.js";

export const router = express.Router();

router.get("/", (_req, res) => {
  const summary = getHealthSummary();
  res.json(
    buildRuntimeHealthResponse(getRuntimeContext(), {
      metadata: {
        runtime_status: summary.runtimeStatus,
        mqtt_connected: summary.mqttConnected,
        configured_devices: summary.configuredDevices,
        connected_devices: summary.connectedDevices,
        devices_with_current_fix: summary.devicesWithCurrentFix,
        devices_with_stale_fix: summary.devicesWithStaleFix,
        last_error: summary.lastError,
      },
    }),
  );
});
