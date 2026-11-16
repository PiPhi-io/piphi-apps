import assert from "node:assert/strict";
import test from "node:test";

import type { EventMessage, ServerInfoMessage } from "@matter-server/ws-client";

import { assertServerCompatibility, toPublicMatterEvent } from "../src/matterjs-backend.js";

test("Matter Server schema compatibility fails closed", () => {
  const serverInfo = {
    schema_version: 15,
    min_supported_schema_version: 11,
  } as ServerInfoMessage;
  assert.doesNotThrow(() => assertServerCompatibility(serverInfo));
  assert.throws(
    () => assertServerCompatibility({ ...serverInfo, schema_version: 12 }),
    /Unsupported Matter Server WebSocket schema/,
  );
  assert.throws(
    () => assertServerCompatibility({ ...serverInfo, min_supported_schema_version: 16 }),
    /Unsupported Matter Server WebSocket schema/,
  );
});

test("node snapshots are reduced to an allow-listed public event", () => {
  const canary = "wifi-password-canary";
  const event = {
    event: "node_updated",
    data: {
      node_id: 1234n,
      available: true,
      date_commissioned: "2026-11-15T00:00:00Z",
      is_bridge: false,
      attributes: {
        "0/49/0": canary,
        "0/62/3": "private-key-canary",
        "1/6/0": true,
      },
    },
  } as unknown as EventMessage;

  const publicEvent = toPublicMatterEvent(event);
  assert.deepEqual(publicEvent, {
    type: "matter.node_updated",
    nodeId: "1234",
    payload: {
      available: true,
      date_commissioned: "2026-11-15T00:00:00Z",
      is_bridge: false,
    },
  });
  assert.doesNotMatch(JSON.stringify(publicEvent), new RegExp(canary));
});

test("sensitive and root attributes never become public state events", () => {
  const sensitive = {
    event: "attribute_updated",
    data: [1234n, "1/49/0", "thread-dataset-canary"],
  } as unknown as EventMessage;
  const root = {
    event: "attribute_updated",
    data: [1234n, "0/40/1", "root-metadata"],
  } as unknown as EventMessage;

  assert.equal(toPublicMatterEvent(sensitive), undefined);
  assert.equal(toPublicMatterEvent(root), undefined);
});

test("unknown upstream events fail closed", () => {
  const unknown = {
    event: "future_event_with_secrets",
    data: { credentials: "canary-secret" },
  } as unknown as EventMessage;

  assert.equal(toPublicMatterEvent(unknown), undefined);
});
