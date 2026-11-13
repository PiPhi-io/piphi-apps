import { ZWAVE_EVENT_SCHEMA, type ZWaveTransportEvent } from "./types.js";

const SENSITIVE_KEY = /(security|network.?key|credential|token|secret|password|dsk|raw.?frame|nvm)/i;

export class BoundedEventBuffer {
  readonly capacity: number;
  private readonly events: ZWaveTransportEvent[] = [];
  private nextSequence = 1;
  dropped = 0;

  constructor(capacity = 1_000) {
    if (!Number.isInteger(capacity) || capacity < 10 || capacity > 10_000) {
      throw new Error("event_queue_capacity must be an integer between 10 and 10000");
    }
    this.capacity = capacity;
  }

  append(event: Omit<ZWaveTransportEvent, "sequence">): ZWaveTransportEvent {
    const record = { ...event, sequence: this.nextSequence++ };
    if (this.events.length === this.capacity) {
      this.events.shift();
      this.dropped += 1;
    }
    this.events.push(record);
    return record;
  }

  read(after = 0, limit = 100): { events: ZWaveTransportEvent[]; next_cursor: number; dropped: number } {
    const boundedLimit = Math.max(1, Math.min(500, Math.trunc(limit)));
    const events = this.events.filter((event) => event.sequence > after).slice(0, boundedLimit);
    return {
      events,
      next_cursor: events.at(-1)?.sequence ?? after,
      dropped: this.dropped,
    };
  }

  get depth(): number {
    return this.events.length;
  }

  get lastSequence(): number {
    return this.nextSequence - 1;
  }
}

export class SerialCommandQueue {
  readonly capacity: number;
  private pending = 0;
  private tail: Promise<void> = Promise.resolve();

  constructor(capacity = 100) {
    if (!Number.isInteger(capacity) || capacity < 1 || capacity > 1_000) {
      throw new Error("command_queue_capacity must be an integer between 1 and 1000");
    }
    this.capacity = capacity;
  }

  async submit<T>(operation: () => Promise<T>): Promise<T> {
    if (this.pending >= this.capacity) {
      throw new Error("command_queue_saturated");
    }
    this.pending += 1;
    const previous = this.tail;
    let release!: () => void;
    this.tail = new Promise<void>((resolve) => { release = resolve; });
    await previous;
    try {
      return await operation();
    } finally {
      this.pending -= 1;
      release();
    }
  }

  get depth(): number {
    return this.pending;
  }
}

export function sanitizeZWaveValue(value: unknown, key = ""): unknown {
  return sanitizeValue(value, key, 0, new WeakSet<object>());
}

function sanitizeValue(value: unknown, key: string, depth: number, seen: WeakSet<object>): unknown {
  if (SENSITIVE_KEY.test(key)) return "[redacted]";
  if (depth > 5) return "[truncated]";
  if (value == null || typeof value === "boolean") return value;
  if (typeof value === "string") return value.length > 4_096 ? `${value.slice(0, 4_096)}[truncated]` : value;
  if (typeof value === "number") return Number.isFinite(value) ? value : String(value);
  if (typeof value === "bigint") return value.toString();
  if (value instanceof Date) return value.toISOString();
  if (value instanceof Uint8Array || Buffer.isBuffer(value)) return `[binary:${value.byteLength}]`;
  if (typeof value === "object") {
    if (seen.has(value)) return "[circular]";
    seen.add(value);
    if (Array.isArray(value)) {
      return value.slice(0, 100).map((item) => sanitizeValue(item, key, depth + 1, seen));
    }
    const output: Record<string, unknown> = {};
    for (const [childKey, childValue] of Object.entries(value as Record<string, unknown>).slice(0, 100)) {
      output[childKey] = sanitizeValue(childValue, childKey, depth + 1, seen);
    }
    return output;
  }
  return String(value);
}

export function normalizeNodeEvent(
  eventType: string,
  node: Record<string, unknown>,
  args: unknown[] = [],
): Omit<ZWaveTransportEvent, "sequence"> {
  const occurredAt = new Date().toISOString();
  const first = args[0] && typeof args[0] === "object"
    ? args[0] as Record<string, unknown>
    : {};
  const commandClass = numberValue(first.commandClass ?? first.command_class);
  const endpoint = numberValue(first.endpoint) ?? 0;
  const property = first.property;
  const payload = sanitizeZWaveValue({
    ...first,
    ...(args.length > 1 ? { additional: args.slice(1) } : {}),
  }) as Record<string, unknown>;
  const valueId = commandClass != null && property != null
    ? {
        command_class: commandClass,
        endpoint,
        property: property as string | number,
        ...(first.propertyKey != null ? { property_key: first.propertyKey as string | number } : {}),
        ...(typeof first.propertyName === "string" ? { property_name: first.propertyName } : {}),
        ...(typeof first.propertyKeyName === "string" ? { property_key_name: first.propertyKeyName } : {}),
      }
    : undefined;
  return {
    schema_version: ZWAVE_EVENT_SCHEMA,
    occurred_at: occurredAt,
    event_type: `node.${eventType.replaceAll(" ", "_")}`,
    source: "zwave-js",
    ...(numberValue(node.id) != null ? { node_id: numberValue(node.id)! } : {}),
    ...(endpoint != null ? { endpoint } : {}),
    ...(commandClass != null ? { command_class: commandClass } : {}),
    ...(valueId ? { value_id: valueId } : {}),
    payload,
  };
}

function numberValue(value: unknown): number | undefined {
  return typeof value === "number" && Number.isFinite(value) ? value : undefined;
}
