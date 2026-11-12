import express from "express";
import { buildRuntimeDiagnosticsResponse } from "piphi-runtime-kit-node";

import { getDiagnosticsSummary, getRuntimeContext } from "../../lib/runtime.js";

export const router = express.Router();

router.get("/diagnostics", (_req, res) => {
  res.json(
    buildRuntimeDiagnosticsResponse(getRuntimeContext(), {
      diagnostics: getDiagnosticsSummary(),
    }),
  );
});
