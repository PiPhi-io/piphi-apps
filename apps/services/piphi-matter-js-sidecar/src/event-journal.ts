import { randomUUID } from "node:crypto";

import type { JsonObject, MatterEvent } from "./types.js";

export interface SequencedMatterEvent extends MatterEvent {
  sequence: number;
}

export class MatterEventJournal {
  readonly streamId = randomUUID();
  readonly #events: SequencedMatterEvent[] = [];
  #latestSequence = 0;
  #dropped = 0;

  constructor(readonly capacity = 1000) {
    if (!Number.isInteger(capacity) || capacity < 1) throw new RangeError("Event journal capacity must be positive");
  }

  get size(): number { return this.#events.length; }
  get latestSequence(): number { return this.#latestSequence; }
  get dropped(): number { return this.#dropped; }

  append(event: MatterEvent): SequencedMatterEvent {
    const record = { ...event, sequence: ++this.#latestSequence };
    this.#events.push(record);
    if (this.#events.length > this.capacity) {
      const dropped = this.#events.length - this.capacity;
      this.#events.splice(0, dropped);
      this.#dropped += dropped;
    }
    return record;
  }

  legacyEvents(after?: string): SequencedMatterEvent[] {
    if (!after) return [...this.#events];
    const index = this.#events.findIndex((event) => event.id === after);
    if (index < 0) {
      throw new EventCursorExpiredError(
        after,
        this.#events[0]?.id,
        this.#events.at(-1)?.id,
        this.#dropped,
      );
    }
    return this.#events.slice(index + 1);
  }

  page(after = 0, limit = 100): JsonObject {
    if (!Number.isInteger(after) || after < 0) throw new RangeError("after must be a non-negative integer");
    if (!Number.isInteger(limit) || limit < 1 || limit > 500) throw new RangeError("limit must be between 1 and 500");
    const firstSequence = this.#events[0]?.sequence ?? this.#latestSequence + 1;
    const gap = after > this.#latestSequence || after < firstSequence - 1;
    const events = gap
      ? []
      : this.#events.filter((event) => event.sequence > after).slice(0, limit);
    return {
      schema_version: "piphi.matter.events.v1",
      stream_id: this.streamId,
      first_sequence: firstSequence,
      latest_sequence: this.#latestSequence,
      next_cursor: events.at(-1)?.sequence ?? after,
      dropped_event_count: this.#dropped,
      gap,
      events,
    };
  }
}

export class EventCursorExpiredError extends Error {
  constructor(
    readonly cursor: string,
    readonly oldestCursor: string | undefined,
    readonly latestCursor: string | undefined,
    readonly droppedEventCount: number,
  ) {
    super("Matter event cursor is unknown or has expired; fetch a full snapshot before resuming.");
    this.name = "EventCursorExpiredError";
  }
}
