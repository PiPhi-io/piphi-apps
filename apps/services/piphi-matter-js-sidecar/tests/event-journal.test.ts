import assert from "node:assert/strict";
import test from "node:test";

import { MatterEventJournal } from "../src/event-journal.js";

test("sequenced event pages make overflow and restart recovery explicit", () => {
  const journal = new MatterEventJournal(2);
  for (let index = 0; index < 3; index += 1) {
    journal.append({
      id: `event-${index}`,
      type: "device.state_changed",
      timestamp: new Date(index).toISOString(),
      payload: { index },
    });
  }

  const gap = journal.page(0, 100);
  assert.equal(gap.gap, true);
  assert.equal(gap.dropped_event_count, 1);
  assert.deepEqual(gap.events, []);

  const page = journal.page(1, 1);
  assert.equal(page.gap, false);
  assert.equal(page.next_cursor, 2);
  assert.equal((page.events as Array<{ sequence: number }>)[0]?.sequence, 2);
  assert.notEqual(new MatterEventJournal().streamId, journal.streamId);
});
