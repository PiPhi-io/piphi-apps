import express from "express";
import { buildEventListResponse } from "piphi-runtime-kit-node";

import { getRecentEvents } from "../../lib/runtime.js";

export const router = express.Router();

router.get("/events", (req, res) => {
  const limit = Number(req.query.limit || 50);
  res.json(buildEventListResponse(getRecentEvents(Number.isFinite(limit) ? limit : 50)));
});
