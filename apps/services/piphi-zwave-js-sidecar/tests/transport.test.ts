import assert from "node:assert/strict";
import fs from "node:fs";
import test from "node:test";

import { BoundedEventBuffer, normalizeNodeEvent, sanitizeZWaveValue } from "../src/transport.js";

type Fixture = {
  id: string;
  node_id: number;
  event_type: string;
  args: Record<string, unknown>[];
};

const fixtures = JSON.parse(
  fs.readFileSync("tests/fixtures/realistic-device-events.json", "utf8"),
) as { cases: Fixture[] };

test("normalizes realistic Z-Wave JS device values into the stable transport schema", () => {
  for (const fixture of fixtures.cases) {
    const event = normalizeNodeEvent(fixture.event_type, { id: fixture.node_id }, fixture.args);
    assert.equal(event.schema_version, "piphi.zwave.event.v1", fixture.id);
    assert.equal(event.event_type, "node.value_updated", fixture.id);
    assert.equal(event.node_id, fixture.node_id, fixture.id);
    assert.equal(event.command_class, fixture.args[0]?.commandClass, fixture.id);
    assert.equal(event.value_id?.property, fixture.args[0]?.property, fixture.id);
    assert.deepEqual(event.payload.newValue, fixture.args[0]?.newValue, fixture.id);
    assert.doesNotMatch(JSON.stringify(event), /network.?key|full.?dsk|raw.?frame|nvm/i, fixture.id);
  }
});

test("recursively redacts secrets and binary serial data", () => {
  const cyclic: Record<string, unknown> = { safe: "visible" };
  cyclic.self = cyclic;
  const sanitized = sanitizeZWaveValue({
    networkKey: "00112233445566778899aabbccddeeff",
    nested: { dsk: "12345-67890-12345-67890-12345-67890-12345-67890" },
    rawFrame: Uint8Array.from([1, 2, 3]),
    cyclic,
  });
  assert.deepEqual(sanitized, {
    networkKey: "[redacted]",
    nested: { dsk: "[redacted]" },
    rawFrame: "[redacted]",
    cyclic: { safe: "visible", self: "[circular]" },
  });
});

test("bounded replay reports overwritten events and monotonic cursors", () => {
  const buffer = new BoundedEventBuffer(10);
  for (let index = 0; index < 12; index += 1) {
    buffer.append({
      schema_version: "piphi.zwave.event.v1",
      occurred_at: `2026-11-13T12:00:${String(index).padStart(2, "0")}.000Z`,
      event_type: "node.value_updated",
      source: "zwave-js",
      payload: { index },
    });
  }
  const replay = buffer.read(0, 500);
  assert.equal(replay.events.length, 10);
  assert.equal(replay.events[0]?.sequence, 3);
  assert.equal(replay.next_cursor, 12);
  assert.equal(replay.dropped, 2);
});
