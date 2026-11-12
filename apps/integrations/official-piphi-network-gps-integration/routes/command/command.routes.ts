import express from "express";

import { getGPSDevicePaths, refreshGPSDevice } from "../../lib/gps.js";

export const router = express.Router();

router.post("/command", async (req, res) => {
  const command = (req.body as { command?: string } | undefined)?.command;

  if (command === "refresh") {
    const result = await refreshGPSDevice((req.body ?? {}) as Record<string, unknown>);
    if (!result.success) {
      return res.status(404).json(result);
    }
    return res.json(result);
  }

  if (command === "rescan_devices") {
    const devices = await getGPSDevicePaths();
    return res.json({ success: true, devices });
  }

  return res.status(400).json({ success: false, message: "Unsupported command" });
});
