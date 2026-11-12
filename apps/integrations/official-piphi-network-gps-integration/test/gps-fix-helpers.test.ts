import test from "node:test";
import assert from "node:assert/strict";

import {
  buildUnits,
  createInitialFixState,
  deriveFixQuality,
  normalizeFixStatus,
  parseGgaSentence,
  parseGsaSentence,
  parseRmcSentence,
  toIsoTimestamp,
  toTimestampMs,
} from "../lib/gps-fix.js";

test("toIsoTimestamp returns ISO strings for Date values", () => {
  const date = new Date("2026-04-09T10:00:00.000Z");
  assert.equal(toIsoTimestamp(date), "2026-04-09T10:00:00.000Z");
});

test("toIsoTimestamp preserves full timestamp strings", () => {
  assert.equal(toIsoTimestamp("2026-04-09T10:00:00.000Z"), "2026-04-09T10:00:00.000Z");
});

test("toIsoTimestamp converts time-only strings into ISO timestamps", () => {
  const value = toIsoTimestamp("12:34:56.789");
  assert.match(value, /^\d{4}-\d{2}-\d{2}T12:34:56\.789Z$/);
});

test("toIsoTimestamp falls back to now for unsupported values", () => {
  const value = toIsoTimestamp(undefined);
  assert.match(value, /^\d{4}-\d{2}-\d{2}T/);
});

test("toTimestampMs returns milliseconds for Date values", () => {
  const date = new Date("2026-04-09T10:00:00.000Z");
  assert.equal(toTimestampMs(date), date.getTime());
});

test("toTimestampMs returns milliseconds for timestamp strings", () => {
  assert.equal(toTimestampMs("2026-04-09T10:00:00.000Z"), Date.parse("2026-04-09T10:00:00.000Z"));
});

test("toTimestampMs falls back to now for invalid values", () => {
  const before = Date.now();
  const result = toTimestampMs("not-a-date");
  assert.ok(result >= before);
});

test("normalizeFixStatus maps empty values to searching", () => {
  assert.equal(normalizeFixStatus(""), "searching");
});

test("normalizeFixStatus maps invalid to searching", () => {
  assert.equal(normalizeFixStatus("invalid"), "searching");
});

test("normalizeFixStatus keeps valid values", () => {
  assert.equal(normalizeFixStatus("valid"), "valid");
});

test("normalizeFixStatus maps numeric 3 to 3d", () => {
  assert.equal(normalizeFixStatus("3"), "3d");
});

test("normalizeFixStatus preserves unknown custom statuses", () => {
  assert.equal(normalizeFixStatus("dgps"), "dgps");
});

test("deriveFixQuality returns stale when signal is stale", () => {
  assert.equal(deriveFixQuality("valid", 8, 0.9, "stale"), "stale");
});

test("deriveFixQuality returns searching when signal is not fixed", () => {
  assert.equal(deriveFixQuality("valid", 8, 0.9, "searching"), "searching");
});

test("deriveFixQuality returns excellent for dgps", () => {
  assert.equal(deriveFixQuality("dgps", 8, 0.9, "fixed"), "excellent");
});

test("deriveFixQuality returns strong for low hdop and many satellites", () => {
  assert.equal(deriveFixQuality("valid", 7, 1.2, "fixed"), "strong");
});

test("deriveFixQuality returns good for moderate hdop", () => {
  assert.equal(deriveFixQuality("valid", 5, 2.5, "fixed"), "good");
});

test("deriveFixQuality returns usable for enough satellites without hdop", () => {
  assert.equal(deriveFixQuality("valid", 3, null, "fixed"), "usable");
});

test("deriveFixQuality returns weak for low confidence fixes", () => {
  assert.equal(deriveFixQuality("valid", 2, 5, "fixed"), "weak");
});

test("buildUnits only includes units for present metrics", () => {
  assert.deepEqual(
    buildUnits({
      latitude: 48.1,
      longitude: 11.5,
      satellites: 8,
    }),
    {
      latitude: "degrees",
      longitude: "degrees",
      satellites: "count",
    },
  );
});

test("buildUnits includes fix age and speed units", () => {
  assert.deepEqual(
    buildUnits({
      speed_knots: 22.4,
      fix_age_ms: 3000,
    }),
    {
      speed_knots: "kn",
      fix_age_ms: "ms",
    },
  );
});

test("parseRmcSentence normalizes coordinates and speed", () => {
  const snapshot = parseRmcSentence({
    datetime: "2026-04-09T10:00:00.000Z",
    latitude: 48.1173,
    longitude: 11.5167,
    speedKnots: 20.1,
    status: "A",
  });
  assert.equal(snapshot.source, "rmc");
  assert.equal(snapshot.latitude, 48.1173);
  assert.equal(snapshot.longitude, 11.5167);
  assert.equal(snapshot.speedKnots, 20.1);
  assert.equal(snapshot.status, "a");
});

test("parseRmcSentence nulls non-numeric coordinates", () => {
  const snapshot = parseRmcSentence({
    datetime: "2026-04-09T10:00:00.000Z",
    latitude: Number.NaN,
    longitude: Infinity,
  });
  assert.equal(snapshot.latitude, null);
  assert.equal(snapshot.longitude, null);
});

test("parseGgaSentence keeps valid position data for fixed sentences", () => {
  const snapshot = parseGgaSentence({
    time: "2026-04-09T10:00:01.000Z",
    fixType: "1",
    latitude: 48.1173,
    longitude: 11.5167,
    satellitesInView: 8,
    horizontalDilution: 0.9,
    altitudeMeters: 545.4,
  });
  assert.equal(snapshot.fixType, "1");
  assert.equal(snapshot.latitude, 48.1173);
  assert.equal(snapshot.altitudeMeters, 545.4);
});

test("parseGgaSentence clears position data for searching fixes", () => {
  const snapshot = parseGgaSentence({
    time: "2026-04-09T10:00:01.000Z",
    fixType: "0",
    latitude: 48.1173,
    longitude: 11.5167,
    altitudeMeters: 545.4,
  });
  assert.equal(snapshot.fixType, "0");
  assert.equal(snapshot.latitude, 48.1173);
  assert.equal(snapshot.longitude, 11.5167);
});

test("parseGsaSentence uses provided now value", () => {
  const snapshot = parseGsaSentence(
    {
      HDOP: 1.5,
      PDOP: 1.8,
      VDOP: 0.9,
      fixMode: "3",
    },
    123456,
  );
  assert.equal(snapshot.tsMs, 123456);
  assert.equal(snapshot.fixType, "3d");
});

test("createInitialFixState starts with idle defaults", () => {
  assert.deepEqual(createInitialFixState(), {
    rmc: null,
    gga: null,
    gsa: null,
    signalState: "idle",
    fixStatus: "idle",
    fixQuality: "unknown",
    lastGoodFix: null,
  });
});
