#!/usr/bin/env node

import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { pathToFileURL } from "node:url";

const FORBIDDEN_KEYS = /(?:password|credential|operational_dataset|setup_payload|token|fabric_key|private_key|ip_address)/i;

const nonEmpty = (value, label) => {
  assert.equal(typeof value, "string", `${label} must be a string`);
  assert.ok(value.trim(), `${label} must not be empty`);
};

export function validateHardwareReport(report, ledger) {
  assert.ok(report && typeof report === "object" && !Array.isArray(report), "report must be an object");
  assert.equal(report.schema_version, 1, "unsupported hardware report schema");
  assert.equal(report.release, ledger.release, "report release does not match the qualification ledger");
  assert.ok(ledger.policy.required_profiles.includes(report.profile_id), "report profile is not required by the ledger");
  assert.ok(["qualified", "failed", "blocked"].includes(report.result), "invalid hardware qualification result");

  for (const [key] of walk(report)) {
    assert.ok(!FORBIDDEN_KEYS.test(key), `hardware report contains forbidden key: ${key}`);
  }
  const serialized = JSON.stringify(report);
  assert.ok(!serialized.includes("MT:"), "hardware report contains a Matter setup payload");

  assert.ok(report.device && typeof report.device === "object", "device metadata is required");
  for (const field of ["vendor", "model", "hardware_revision", "firmware_version", "transport"]) {
    nonEmpty(report.device[field], `device.${field}`);
  }
  const profile = ledger.profiles.find((candidate) => candidate.id === report.profile_id);
  assert.equal(report.device.transport, profile.transport, "device transport does not match its profile");

  assert.ok(report.environment && typeof report.environment === "object", "environment metadata is required");
  nonEmpty(report.environment.host_os, "environment.host_os");
  nonEmpty(report.environment.network_summary, "environment.network_summary");
  assert.match(report.environment.image_digest ?? "", /^sha256:[a-f0-9]{64}$/, "invalid release image digest");
  assert.match(report.controller_identity_hash ?? "", /^[a-f0-9]{16}$/, "invalid hashed controller identity");

  assert.ok(report.run && typeof report.run === "object", "run metadata is required");
  nonEmpty(report.run.operator, "run.operator");
  const startedAt = Date.parse(report.run.started_at);
  const completedAt = Date.parse(report.run.completed_at);
  assert.ok(Number.isFinite(startedAt), "run.started_at must be an ISO timestamp");
  assert.ok(Number.isFinite(completedAt), "run.completed_at must be an ISO timestamp");
  assert.ok(completedAt >= startedAt, "run.completed_at precedes run.started_at");

  assert.ok(Array.isArray(report.steps), "report steps are required");
  assert.equal(new Set(report.steps.map((step) => step.id)).size, report.steps.length, "report contains duplicate steps");
  const byId = new Map(report.steps.map((step) => [step.id, step]));
  const allowedSteps = [
    ...ledger.policy.qualification_steps,
    ...(ledger.policy.optional_qualification_steps ?? []),
  ];
  for (const required of ledger.policy.qualification_steps) {
    const step = byId.get(required);
    assert.ok(step, `hardware report is missing step: ${required}`);
    assert.ok(["pass", "fail", "blocked"].includes(step.status), `invalid status for step: ${required}`);
    nonEmpty(step.evidence, `step ${required} evidence`);
  }
  for (const step of report.steps) {
    assert.ok(allowedSteps.includes(step.id), `unknown qualification step: ${step.id}`);
  }

  if (report.result === "qualified") {
    assert.ok(report.steps.every((step) => step.status === "pass"), "qualified reports require every step to pass");
  } else if (report.result === "failed") {
    assert.ok(report.steps.some((step) => step.status === "fail"), "failed reports require a failed step");
  } else {
    assert.ok(report.steps.some((step) => step.status === "blocked"), "blocked reports require a blocked step");
  }
  assert.ok(Array.isArray(report.evidence_artifacts) && report.evidence_artifacts.length > 0, "evidence artifacts are required");
  for (const artifact of report.evidence_artifacts) nonEmpty(artifact, "evidence artifact");

  return {
    profile_id: report.profile_id,
    result: report.result,
    release: report.release,
    device: `${report.device.vendor} ${report.device.model}`,
    completed_at: report.run.completed_at,
    controller_identity_hash: report.controller_identity_hash,
  };
}

export function selfTestHardwareReportValidator(ledger) {
  const report = {
    schema_version: 1,
    release: ledger.release,
    profile_id: ledger.policy.required_profiles[0],
    result: "qualified",
    device: {
      vendor: "Example vendor",
      model: "Example device",
      hardware_revision: "1",
      firmware_version: "1.0",
      transport: ledger.profiles[0].transport,
    },
    environment: {
      image_digest: `sha256:${"a".repeat(64)}`,
      host_os: "Example Linux host",
      network_summary: "Isolated qualification LAN; addresses redacted",
    },
    controller_identity_hash: "0123456789abcdef",
    run: {
      operator: "Example operator",
      started_at: "2026-11-15T00:00:00.000Z",
      completed_at: "2026-11-15T00:10:00.000Z",
    },
    steps: ledger.policy.qualification_steps.map((id) => ({ id, status: "pass", evidence: `Example ${id} evidence` })),
    evidence_artifacts: ["docs/qualification/example-redacted.log"],
  };
  assert.equal(validateHardwareReport(report, ledger).result, "qualified");
  assert.throws(() => validateHardwareReport({ ...report, setup_payload: "redacted" }, ledger), /forbidden key/);
  assert.throws(() => validateHardwareReport({ ...report, result: "qualified", steps: report.steps.slice(1) }, ledger), /missing step/);
}

function* walk(value) {
  if (!value || typeof value !== "object") return;
  for (const [key, child] of Object.entries(value)) {
    yield [key, child];
    yield* walk(child);
  }
}

async function main() {
  const reportPath = process.argv[2];
  if (!reportPath) throw new Error("Usage: npm run validate:hardware-report -- <report.json>");
  const [report, ledger] = await Promise.all([
    readFile(reportPath, "utf8").then(JSON.parse),
    readFile(new URL("../docs/hardware-qualification.json", import.meta.url), "utf8").then(JSON.parse),
  ]);
  console.log(JSON.stringify(validateHardwareReport(report, ledger), null, 2));
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) await main();
