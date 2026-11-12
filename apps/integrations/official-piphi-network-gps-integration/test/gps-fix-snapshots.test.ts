import test from "node:test";
import assert from "node:assert/strict";

import {
  applyParsedSentenceToFixState,
  createInitialFixState,
  createMergedFixSnapshot,
  processNmeaSentence,
  type FixState,
} from "../lib/gps-fix.js";
import {
  assertApproximate,
  buildGgaSentence,
  buildGsaSentence,
  buildRmcSentence,
  createUtcDateWithOffset,
} from "./gps-fixture-helpers.js";

test("createMergedFixSnapshot returns searching for an empty fix state", () => {
  const snapshot = createMergedFixSnapshot(createInitialFixState(), Date.now());
  assert.equal(snapshot.signalState, "searching");
  assert.equal(snapshot.metrics.fix_status, "searching");
});

test("createMergedFixSnapshot uses a fresh RMC fix without GGA", () => {
  const now = createUtcDateWithOffset(0);
  const result = processNmeaSentence(createInitialFixState(), buildRmcSentence(now), now.getTime());
  assert.equal(result.snapshot?.signalState, "fixed");
  assert.equal(result.snapshot?.metrics.position_source, "rmc");
});

test("createMergedFixSnapshot uses fresh GGA coordinates when RMC is missing", () => {
  const date = createUtcDateWithOffset(0);
  const now = date.getTime();
  const result = applyParsedSentenceToFixState(
    createInitialFixState(),
    {
      sentenceId: "GGA",
      time: date.toISOString(),
      latitude: 48.1173,
      longitude: 11.5167,
      satellitesInView: 8,
      horizontalDilution: 0.8,
      altitudeMeters: 545.4,
      fixType: "1",
    },
    now,
  );

  assert.equal(result.snapshot?.signalState, "fixed");
  assert.equal(result.snapshot?.metrics.position_source, "gga");
  assert.equal(result.snapshot?.metrics.fix_status, "1");
});

test("createMergedFixSnapshot prefers newer GGA coordinates over older RMC coordinates", () => {
  const older = createUtcDateWithOffset(0);
  const newer = createUtcDateWithOffset(2);
  const afterRmc = processNmeaSentence(createInitialFixState(), buildRmcSentence(older), older.getTime());
  const afterGga = processNmeaSentence(afterRmc.fixState, buildGgaSentence(newer), newer.getTime());

  assert.equal(afterGga.snapshot?.metrics.position_source, "gga");
  assert.equal(afterGga.snapshot?.timestamp, newer.toISOString());
});

test("createMergedFixSnapshot keeps newest sentence timestamp in fix details", () => {
  const older = createUtcDateWithOffset(0);
  const newer = createUtcDateWithOffset(1);
  const afterRmc = processNmeaSentence(createInitialFixState(), buildRmcSentence(older), older.getTime());
  const afterGsa = processNmeaSentence(afterRmc.fixState, buildGsaSentence(), newer.getTime());

  assert.equal(afterGsa.snapshot?.fixDetails.last_sentence_at, new Date(newer.getTime()).toISOString());
});

test("applyParsedSentenceToFixState returns null snapshot for unsupported sentences", () => {
  const result = applyParsedSentenceToFixState(
    createInitialFixState(),
    { sentenceId: "GLL" },
    Date.now(),
  );
  assert.equal(result.snapshot, null);
  assert.equal(result.fixState.signalState, "idle");
});

test("applyParsedSentenceToFixState stores lastGoodFix after a fixed snapshot", () => {
  const now = createUtcDateWithOffset(0);
  const result = processNmeaSentence(createInitialFixState(), buildRmcSentence(now), now.getTime());
  assert.ok(result.fixState.lastGoodFix);
  assert.equal(result.fixState.lastGoodFix?.signalState, "fixed");
});

test("applyParsedSentenceToFixState preserves previous lastGoodFix on unsupported sentences", () => {
  const now = createUtcDateWithOffset(0);
  const fixed = processNmeaSentence(createInitialFixState(), buildRmcSentence(now), now.getTime());
  const afterUnknown = applyParsedSentenceToFixState(
    fixed.fixState,
    { sentenceId: "GLL" },
    now.getTime() + 1000,
  );
  assert.equal(afterUnknown.fixState.lastGoodFix?.timestamp, fixed.fixState.lastGoodFix?.timestamp);
});

test("processNmeaSentence throws on invalid NMEA input", () => {
  assert.throws(() => processNmeaSentence(createInitialFixState(), "$GPGARBAGE", Date.now()));
});

test("GSA-only updates keep searching without coordinates", () => {
  const now = Date.now();
  const result = applyParsedSentenceToFixState(
    createInitialFixState(),
    {
      sentenceId: "GSA",
      HDOP: 1.2,
      PDOP: 1.4,
      VDOP: 0.8,
      fixMode: "3",
    },
    now,
  );
  assert.equal(result.snapshot?.signalState, "searching");
  assert.equal(result.snapshot?.metrics.hdop, 1.2);
});

test("stale snapshots inherit last known coordinates", () => {
  const now = createUtcDateWithOffset(0);
  const fixed = processNmeaSentence(createInitialFixState(), buildRmcSentence(now), now.getTime());
  const stale = createMergedFixSnapshot(fixed.fixState, now.getTime() + 20000);

  assert.equal(stale.signalState, "stale");
  assertApproximate(stale.metrics.latitude as number, 48.1173);
  assert.equal(stale.metrics.position_source, "last_known");
});

test("expired last known fixes return to searching", () => {
  const now = createUtcDateWithOffset(0);
  const fixed = processNmeaSentence(createInitialFixState(), buildRmcSentence(now), now.getTime());
  const expired = createMergedFixSnapshot(fixed.fixState, now.getTime() + 181000);

  assert.equal(expired.signalState, "searching");
  assert.equal(expired.metrics.position_source, "none");
});

test("searching snapshots still preserve fresh satellites from GGA", () => {
  const date = createUtcDateWithOffset(0);
  const now = date.getTime();
  const result = applyParsedSentenceToFixState(
    createInitialFixState(),
    {
      sentenceId: "GGA",
      time: date.toISOString(),
      satellitesInView: 5,
      horizontalDilution: 1.2,
      fixType: "0",
    },
    now,
  );

  assert.equal(result.snapshot?.signalState, "searching");
  assert.equal(result.snapshot?.metrics.satellites, 5);
  assert.equal(result.snapshot?.metrics.hdop, 1.2);
});

test("searching snapshots prefer fresh GSA hdop when GGA hdop is unavailable", () => {
  const now = Date.now();
  const afterGsa = applyParsedSentenceToFixState(
    createInitialFixState(),
    { sentenceId: "GSA", HDOP: 1.1, fixMode: "3" },
    now,
  );

  assert.equal(afterGsa.snapshot?.metrics.hdop, 1.1);
});

test("fixed snapshots include altitude from GGA", () => {
  const older = createUtcDateWithOffset(0);
  const newer = createUtcDateWithOffset(1);
  const afterRmc = processNmeaSentence(createInitialFixState(), buildRmcSentence(older), older.getTime());
  const afterGga = processNmeaSentence(afterRmc.fixState, buildGgaSentence(newer), newer.getTime());
  assert.equal(afterGga.snapshot?.metrics.altitude_meters, 545.4);
});

test("fixed snapshots include speed from RMC when GGA is newer", () => {
  const older = createUtcDateWithOffset(0);
  const newer = createUtcDateWithOffset(1);
  const afterRmc = processNmeaSentence(createInitialFixState(), buildRmcSentence(older), older.getTime());
  const afterGga = processNmeaSentence(afterRmc.fixState, buildGgaSentence(newer), newer.getTime());
  assert.equal(afterGga.snapshot?.metrics.speed_knots, 22.4);
});

test("stale snapshots keep updated hdop from fresher GSA data", () => {
  const initial = createUtcDateWithOffset(0);
  const afterRmc = processNmeaSentence(createInitialFixState(), buildRmcSentence(initial), initial.getTime());
  const afterGsa = processNmeaSentence(afterRmc.fixState, buildGsaSentence("3", "2.2"), initial.getTime() + 1000);
  const stale = createMergedFixSnapshot(afterGsa.fixState, initial.getTime() + 20000);
  assert.equal(stale.metrics.hdop, 2.2);
});

test("last_valid_fix_at remains the last good fix timestamp when stale", () => {
  const initial = createUtcDateWithOffset(0);
  const fixed = processNmeaSentence(createInitialFixState(), buildRmcSentence(initial), initial.getTime());
  const stale = createMergedFixSnapshot(fixed.fixState, initial.getTime() + 20000);
  assert.equal(stale.fixDetails.last_valid_fix_at, fixed.snapshot?.timestamp);
});

test("snapshot fix age is non-negative for fixed snapshots", () => {
  const initial = createUtcDateWithOffset(0);
  const fixed = processNmeaSentence(createInitialFixState(), buildRmcSentence(initial), initial.getTime());
  assert.ok((fixed.snapshot?.metrics.fix_age_ms ?? -1) >= 0);
});

test("snapshot fix age grows for stale snapshots", () => {
  const initial = createUtcDateWithOffset(0);
  const fixed = processNmeaSentence(createInitialFixState(), buildRmcSentence(initial), initial.getTime());
  const stale = createMergedFixSnapshot(fixed.fixState, initial.getTime() + 30000);
  assert.ok((stale.metrics.fix_age_ms ?? 0) >= 30000);
});

test("applying a GSA after a fixed RMC upgrades fix status to 3d", () => {
  const initial = createUtcDateWithOffset(0);
  const afterRmc = processNmeaSentence(createInitialFixState(), buildRmcSentence(initial), initial.getTime());
  const afterGsa = processNmeaSentence(afterRmc.fixState, buildGsaSentence("3"), initial.getTime() + 1000);
  assert.equal(afterGsa.snapshot?.metrics.fix_status, "3d");
});

test("lastGoodFix remains unchanged after searching snapshots", () => {
  const initial = createUtcDateWithOffset(0);
  const fixed = processNmeaSentence(createInitialFixState(), buildRmcSentence(initial), initial.getTime());
  const searching = applyParsedSentenceToFixState(
    fixed.fixState,
    { sentenceId: "GSA", fixMode: "0" },
    initial.getTime() + 200000,
  );
  assert.equal(searching.fixState.lastGoodFix?.timestamp, fixed.fixState.lastGoodFix?.timestamp);
});

test("createMergedFixSnapshot can work from a handcrafted lastGoodFix", () => {
  const baseState: FixState = {
    ...createInitialFixState(),
    lastGoodFix: {
      timestamp: "2026-04-09T10:00:00.000Z",
      tsMs: 1_000,
      signalState: "fixed",
      stale: false,
      metrics: {
        latitude: 48.1173,
        longitude: 11.5167,
        satellites: 7,
        hdop: 0.9,
        altitude_meters: 545.4,
        fix_status: "valid",
        fix_quality: "strong",
        position_source: "rmc",
        fix_age_ms: 0,
      },
      fixDetails: {
        signal_state: "fixed",
        fix_quality: "strong",
        position_source: "rmc",
        stale: false,
        last_sentence_at: "2026-04-09T10:00:00.000Z",
        last_fix_at: "2026-04-09T10:00:00.000Z",
        last_valid_fix_at: "2026-04-09T10:00:00.000Z",
        fix_age_ms: 0,
        satellites: 7,
        hdop: 0.9,
        altitude_meters: 545.4,
      },
    },
    signalState: "fixed",
    fixStatus: "valid",
    fixQuality: "strong",
  };

  const stale = createMergedFixSnapshot(baseState, 20_000);
  assert.equal(stale.signalState, "stale");
  assert.equal(stale.metrics.position_source, "last_known");
});
