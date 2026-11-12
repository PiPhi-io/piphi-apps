import express from "express";
import { buildDiscoveryResponse } from "piphi-runtime-kit-node";
import { getGPSDevicePaths } from "../../lib/gps.js";
export const router = express.Router();
async function handleDiscovery(_req, res) {
    const devices = await getGPSDevicePaths();
    res.json(buildDiscoveryResponse(devices));
}
router.get("/discovery", handleDiscovery);
router.get("/discover", handleDiscovery);
