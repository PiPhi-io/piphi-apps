import test from "node:test";
import assert from "node:assert/strict";
import { CURRENT_FIX_MAX_AGE_MS, STALE_FIX_MAX_AGE_MS, createInitialFixState, createMergedFixSnapshot, processNmeaSentence, } from "../lib/gps-fix.js";
function buildSentence(body) {
    const checksum = [...body]
        .reduce((accumulator, character) => accumulator ^ character.charCodeAt(0), 0)
        .toString(16)
        .toUpperCase()
        .padStart(2, "0");
    return `$${body}*${checksum}`;
}
function formatNmeaDate(date) {
    const day = String(date.getUTCDate()).padStart(2, "0");
    const month = String(date.getUTCMonth() + 1).padStart(2, "0");
    const year = String(date.getUTCFullYear()).slice(-2);
    return `${day}${month}${year}`;
}
function formatNmeaTime(date) {
    const hours = String(date.getUTCHours()).padStart(2, "0");
    const minutes = String(date.getUTCMinutes()).padStart(2, "0");
    const seconds = String(date.getUTCSeconds()).padStart(2, "0");
    return `${hours}${minutes}${seconds}`;
}
function createUtcDateWithOffset(secondsOffset = 0) {
    const date = new Date();
    date.setUTCMilliseconds(0);
    date.setUTCSeconds(date.getUTCSeconds() + secondsOffset);
    return date;
}
function buildRmcSentence(date, status = "A") {
    return buildSentence(`GPRMC,${formatNmeaTime(date)},${status},4807.038,N,01131.000,E,022.4,084.4,${formatNmeaDate(date)},003.1,W`);
}
function buildGgaSentence(date, fixQuality = 1) {
    const latitude = fixQuality === 0 ? "" : "4807.038";
    const northSouth = fixQuality === 0 ? "" : "N";
    const longitude = fixQuality === 0 ? "" : "01131.000";
    const eastWest = fixQuality === 0 ? "" : "E";
    const satellites = fixQuality === 0 ? "00" : "08";
    const hdop = fixQuality === 0 ? "99.9" : "0.9";
    const altitude = fixQuality === 0 ? "" : "545.4";
    return buildSentence(`GPGGA,${formatNmeaTime(date)},${latitude},${northSouth},${longitude},${eastWest},${fixQuality},${satellites},${hdop},${altitude},M,46.9,M,,`);
}
function buildGsaSentence(fixMode = "3") {
    return buildSentence(`GPGSA,A,${fixMode},04,05,09,12,24,25,29,31,,,,1.8,0.9,1.5`);
}
function assertApproximate(actual, expected, epsilon = 0.000001) {
    assert.ok(Math.abs(actual - expected) <= epsilon, `expected ${actual} to be within ${epsilon} of ${expected}`);
}
test("processNmeaSentence parses a valid RMC sentence into a fixed snapshot", () => {
    const fixDate = createUtcDateWithOffset(0);
    const result = processNmeaSentence(createInitialFixState(), buildRmcSentence(fixDate), fixDate.getTime());
    assert.equal(result.snapshot?.signalState, "fixed");
    assert.equal(result.snapshot?.metrics.fix_status, "valid");
    assert.equal(result.snapshot?.metrics.position_source, "rmc");
    assert.equal(result.snapshot?.metrics.speed_knots, 22.4);
    assert.equal(result.fixState.fixStatus, "valid");
    assertApproximate(result.snapshot?.metrics.latitude, 48.1173);
    assertApproximate(result.snapshot?.metrics.longitude, 11.516666666666667);
});
test("RMC and GGA sentences merge into a richer live fix snapshot", () => {
    const rmcDate = createUtcDateWithOffset(0);
    const ggaDate = createUtcDateWithOffset(1);
    const afterRmc = processNmeaSentence(createInitialFixState(), buildRmcSentence(rmcDate), rmcDate.getTime());
    const afterGga = processNmeaSentence(afterRmc.fixState, buildGgaSentence(ggaDate), ggaDate.getTime());
    assert.equal(afterGga.snapshot?.signalState, "fixed");
    assert.equal(afterGga.snapshot?.metrics.fix_status, "fix");
    assert.equal(afterGga.snapshot?.metrics.fix_quality, "strong");
    assert.equal(afterGga.snapshot?.metrics.position_source, "gga");
    assert.equal(afterGga.snapshot?.metrics.satellites, 8);
    assert.equal(afterGga.snapshot?.metrics.hdop, 0.9);
    assert.equal(afterGga.snapshot?.metrics.altitude_meters, 545.4);
});
test("a no-fix GGA sentence does not downgrade a fresh valid RMC fix", () => {
    const rmcDate = createUtcDateWithOffset(0);
    const noFixGgaDate = createUtcDateWithOffset(1);
    const afterRmc = processNmeaSentence(createInitialFixState(), buildRmcSentence(rmcDate), rmcDate.getTime());
    const afterNoFixGga = processNmeaSentence(afterRmc.fixState, buildGgaSentence(noFixGgaDate, 0), noFixGgaDate.getTime());
    assert.equal(afterNoFixGga.snapshot?.signalState, "fixed");
    assert.equal(afterNoFixGga.snapshot?.metrics.fix_status, "valid");
    assert.equal(afterNoFixGga.snapshot?.metrics.position_source, "rmc");
    assertApproximate(afterNoFixGga.snapshot?.metrics.latitude, 48.1173);
    assertApproximate(afterNoFixGga.snapshot?.metrics.longitude, 11.516666666666667);
});
test("a GSA sentence enriches the current fix with HDOP data without hardware access", () => {
    const rmcDate = createUtcDateWithOffset(0);
    const gsaNow = createUtcDateWithOffset(1);
    const afterRmc = processNmeaSentence(createInitialFixState(), buildRmcSentence(rmcDate), rmcDate.getTime());
    const afterGsa = processNmeaSentence(afterRmc.fixState, buildGsaSentence("3"), gsaNow.getTime());
    assert.equal(afterGsa.snapshot?.signalState, "fixed");
    assert.equal(afterGsa.snapshot?.metrics.position_source, "rmc");
    assert.equal(afterGsa.snapshot?.metrics.hdop, 1.5);
    assert.equal(afterGsa.snapshot?.metrics.fix_status, "3d");
});
test("a recent last-known fix becomes stale after live sentence freshness expires", () => {
    const rmcDate = createUtcDateWithOffset(0);
    const ggaDate = createUtcDateWithOffset(1);
    const afterRmc = processNmeaSentence(createInitialFixState(), buildRmcSentence(rmcDate), rmcDate.getTime());
    const afterGga = processNmeaSentence(afterRmc.fixState, buildGgaSentence(ggaDate), ggaDate.getTime());
    const lastGoodFix = afterGga.fixState.lastGoodFix;
    assert.ok(lastGoodFix);
    const staleSnapshot = createMergedFixSnapshot(afterGga.fixState, lastGoodFix.tsMs + CURRENT_FIX_MAX_AGE_MS + 1000);
    assert.equal(staleSnapshot.signalState, "stale");
    assert.equal(staleSnapshot.metrics.fix_status, "stale");
    assert.equal(staleSnapshot.metrics.fix_quality, "stale");
    assert.equal(staleSnapshot.metrics.position_source, "last_known");
    assert.ok((staleSnapshot.metrics.fix_age_ms ?? 0) > CURRENT_FIX_MAX_AGE_MS);
});
test("an old last-known fix eventually returns to searching state", () => {
    const rmcDate = createUtcDateWithOffset(0);
    const ggaDate = createUtcDateWithOffset(1);
    const afterRmc = processNmeaSentence(createInitialFixState(), buildRmcSentence(rmcDate), rmcDate.getTime());
    const afterGga = processNmeaSentence(afterRmc.fixState, buildGgaSentence(ggaDate), ggaDate.getTime());
    const lastGoodFix = afterGga.fixState.lastGoodFix;
    assert.ok(lastGoodFix);
    const expiredSnapshot = createMergedFixSnapshot(afterGga.fixState, lastGoodFix.tsMs + STALE_FIX_MAX_AGE_MS + 1000);
    assert.equal(expiredSnapshot.signalState, "searching");
    assert.equal(expiredSnapshot.metrics.fix_status, "searching");
    assert.equal(expiredSnapshot.metrics.fix_quality, "searching");
    assert.equal(expiredSnapshot.metrics.position_source, "none");
    assert.equal(expiredSnapshot.fixDetails.last_valid_fix_at, lastGoodFix.timestamp);
});
