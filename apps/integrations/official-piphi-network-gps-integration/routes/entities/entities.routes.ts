import express from "express";

import { getEntitiesPayload } from "../../lib/gps.js";

export const router = express.Router();

router.get("/entities", (_req, res) => {
  res.json(getEntitiesPayload());
});
