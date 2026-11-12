import express, { type Request, type Response } from "express";
import { body, validationResult } from "express-validator";
import {
  buildConfigApplyResponse,
  ConfigSyncCoordinator,
  formatConfigApplyLog,
  type RuntimeConfig,
  type RuntimeConfigSnapshot,
} from "piphi-runtime-kit-node";
import {
  formatExpressRuntimeAuthSyncLog,
  syncRuntimeAuthFromExpressRequest,
} from "piphi-runtime-kit-node/adapters/express";

import { configureGPSDevice, deconfigureGPSDevice } from "../../lib/gps.js";
import { getActiveConfigs, getRuntimeContext } from "../../lib/runtime.js";
import { logger } from "../../server.js";

export const router = express.Router();
const configSync = new ConfigSyncCoordinator(getRuntimeContext().processState);

interface GPSRuntimeConfig extends RuntimeConfig {
  path: string;
  config_id?: string;
  container_id?: string | null;
  integration_id?: string | null;
}

const schema = [body("path").not().isEmpty().withMessage("Please select a device before continuing")];

function syncRuntimeAuthFromRequest(req: Request, payload: Record<string, unknown>): void {
  const runtime = getRuntimeContext();
  syncRuntimeAuthFromExpressRequest(
    runtime,
    req,
    typeof payload.container_id === "string" ? payload.container_id : null,
  );
  logger.info(
    formatExpressRuntimeAuthSyncLog(
      req,
      typeof payload.container_id === "string" ? payload.container_id : null,
    ),
  );
}

router.post("/config", schema, async (req: Request, res: Response) => {
  const errors = validationResult(req);
  if (!errors.isEmpty()) {
    return res.status(400).json({ errors: errors.array() });
  }

  const payload = (req.body ?? {}) as Record<string, unknown>;
  syncRuntimeAuthFromRequest(req, payload);

  logger.info(
    formatConfigApplyLog({
      id: String(payload.id ?? payload.path ?? "gps-device"),
      containerId: typeof payload.container_id === "string" ? payload.container_id : null,
      integrationId: null,
      ...payload,
    }),
  );

  const result = await configureGPSDevice(payload);
  return res.json({
    ...buildConfigApplyResponse({
      configId: String(result.device_id ?? payload.id ?? payload.path ?? "gps-device"),
      containerId: typeof payload.container_id === "string" ? payload.container_id : null,
      metadata: {
        path: result.path,
        device: result.device ?? null,
        message: result.message,
      },
    }),
    path: result.path,
    message: result.message,
    device: result.device ?? null,
  });
});

router.post("/config/sync", async (req: Request, res: Response) => {
  const payload = (req.body ?? {}) as Record<string, unknown>;
  syncRuntimeAuthFromRequest(req, payload);

  const snapshot = payload as unknown as RuntimeConfigSnapshot<GPSRuntimeConfig>;
  if (!Array.isArray(snapshot.configs)) {
    return res.status(400).json({
      ok: false,
      error: "configs must be an array",
    });
  }

  const activeConfigIds = getActiveConfigs().map((config) => config.configId);
  const result = await configSync.applySnapshot(snapshot, {
    activeConfigIds,
    applyConfig: async (config) => {
      await configureGPSDevice({
        ...config,
        config_id: config.config_id ?? config.configId ?? config.id,
        container_id: config.container_id ?? config.containerId ?? null,
        integration_id: config.integration_id ?? config.integrationId ?? null,
      });
    },
    removeConfig: async (configId) => {
      const active = getActiveConfigs().find((config) => config.configId === configId);
      if (!active) {
        return false;
      }
      const removed = await deconfigureGPSDevice({
        id: active.deviceId,
        ...(active.path ? { path: active.path } : {}),
      });
      return removed.removed > 0;
    },
    getActiveConfigIds: () => getActiveConfigs().map((config) => config.configId),
  });

  return res.json(result);
});
