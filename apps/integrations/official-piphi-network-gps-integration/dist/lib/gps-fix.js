import nmea from "nmea-simple";
export const CURRENT_FIX_MAX_AGE_MS = 15000;
export const STALE_FIX_MAX_AGE_MS = 180000;
function safeString(value) {
    return typeof value === "string" ? value : "";
}
function normalizeNumber(value) {
    return typeof value === "number" && Number.isFinite(value) ? value : null;
}
export function toIsoTimestamp(value) {
    if (value instanceof Date && !Number.isNaN(value.getTime())) {
        return value.toISOString();
    }
    if (typeof value === "string" && value.length > 0) {
        if (/^\d{2}:\d{2}:\d{2}(\.\d+)?$/.test(value)) {
            const now = new Date();
            const [hours = "0", minutes = "0", secondsWithFraction = "0"] = value.split(":");
            const [seconds = "0", fraction = "0"] = secondsWithFraction.split(".");
            now.setUTCHours(Number(hours), Number(minutes), Number(seconds), Number(fraction.padEnd(3, "0").slice(0, 3)));
            return now.toISOString();
        }
        return value;
    }
    return new Date().toISOString();
}
export function toTimestampMs(value) {
    if (value instanceof Date && !Number.isNaN(value.getTime())) {
        return value.getTime();
    }
    if (typeof value === "string" && value.length > 0) {
        const parsed = Date.parse(value);
        if (!Number.isNaN(parsed)) {
            return parsed;
        }
    }
    return Date.now();
}
function isFreshSnapshot(snapshot, now, maxAgeMs = CURRENT_FIX_MAX_AGE_MS) {
    return Boolean(snapshot && typeof snapshot.tsMs === "number" && now - snapshot.tsMs <= maxAgeMs);
}
export function normalizeFixStatus(value) {
    const fixStatus = safeString(value).trim().toLowerCase();
    if (!fixStatus || fixStatus === "none" || fixStatus === "invalid") {
        return "searching";
    }
    if (fixStatus === "valid") {
        return "valid";
    }
    if (fixStatus === "3") {
        return "3d";
    }
    return fixStatus;
}
export function deriveFixQuality(fixStatus, satellites, hdop, signalState) {
    if (signalState === "stale") {
        return "stale";
    }
    if (signalState !== "fixed") {
        return "searching";
    }
    if (fixStatus === "dgps" || fixStatus === "rtk") {
        return "excellent";
    }
    if (typeof hdop === "number" && hdop <= 1.5 && typeof satellites === "number" && satellites >= 6) {
        return "strong";
    }
    if (typeof hdop === "number" && hdop <= 3 && typeof satellites === "number" && satellites >= 4) {
        return "good";
    }
    if (typeof satellites === "number" && satellites >= 3) {
        return "usable";
    }
    return "weak";
}
export function buildUnits(metrics) {
    const units = {};
    if (metrics.latitude != null)
        units.latitude = "degrees";
    if (metrics.longitude != null)
        units.longitude = "degrees";
    if (metrics.speed_knots != null)
        units.speed_knots = "kn";
    if (metrics.satellites != null)
        units.satellites = "count";
    if (metrics.hdop != null)
        units.hdop = "ratio";
    if (metrics.altitude_meters != null)
        units.altitude_meters = "m";
    if (metrics.fix_age_ms != null)
        units.fix_age_ms = "ms";
    return units;
}
export function parseRmcSentence(parsed) {
    const timestamp = toIsoTimestamp(parsed.datetime);
    return {
        source: "rmc",
        timestamp,
        tsMs: toTimestampMs(timestamp),
        latitude: normalizeNumber(parsed.latitude),
        longitude: normalizeNumber(parsed.longitude),
        speedKnots: normalizeNumber(parsed.speedKnots),
        status: safeString(parsed.status).toLowerCase(),
    };
}
export function parseGgaSentence(parsed) {
    const timestamp = toIsoTimestamp(parsed.time);
    const fixType = normalizeFixStatus(parsed.fixType);
    const hasPosition = fixType !== "searching";
    return {
        source: "gga",
        timestamp,
        tsMs: toTimestampMs(timestamp),
        latitude: hasPosition ? normalizeNumber(parsed.latitude) : null,
        longitude: hasPosition ? normalizeNumber(parsed.longitude) : null,
        satellites: normalizeNumber(parsed.satellitesInView),
        hdop: normalizeNumber(parsed.horizontalDilution),
        altitudeMeters: hasPosition ? normalizeNumber(parsed.altitudeMeters) : null,
        fixType,
    };
}
export function parseGsaSentence(parsed, now = Date.now()) {
    const timestamp = new Date(now).toISOString();
    return {
        source: "gsa",
        timestamp,
        tsMs: now,
        hdop: normalizeNumber(parsed.HDOP),
        pdop: normalizeNumber(parsed.PDOP),
        vdop: normalizeNumber(parsed.VDOP),
        fixType: normalizeFixStatus(parsed.fixMode),
    };
}
function newestSentenceTimestamp(sentences) {
    const newest = sentences
        .filter((value) => Boolean(value))
        .sort((left, right) => right.tsMs - left.tsMs)[0];
    return newest ? newest.timestamp : null;
}
export function createInitialFixState() {
    return {
        rmc: null,
        gga: null,
        gsa: null,
        signalState: "idle",
        fixStatus: "idle",
        fixQuality: "unknown",
        lastGoodFix: null,
    };
}
export function createMergedFixSnapshot(fixState, now = Date.now()) {
    const freshRmc = isFreshSnapshot(fixState.rmc, now) ? fixState.rmc : null;
    const freshGga = isFreshSnapshot(fixState.gga, now) ? fixState.gga : null;
    const freshGsa = isFreshSnapshot(fixState.gsa, now) ? fixState.gsa : null;
    const coordinateCandidates = [freshRmc, freshGga]
        .filter((candidate) => Boolean(candidate && candidate.latitude != null && candidate.longitude != null))
        .sort((left, right) => right.tsMs - left.tsMs);
    const freshestCoordinates = coordinateCandidates[0] ?? null;
    const fixStatus = freshGga?.fixType && freshGga.fixType !== "searching"
        ? normalizeFixStatus(freshGga.fixType)
        : freshGsa?.fixType && freshGsa.fixType !== "searching"
            ? normalizeFixStatus(freshGsa.fixType)
            : freshRmc?.status === "valid"
                ? "valid"
                : "searching";
    const currentFixAvailable = Boolean(freshestCoordinates && (freshRmc?.status === "valid" || fixStatus !== "searching"));
    const currentFixAgeMs = freshestCoordinates ? Math.max(0, now - freshestCoordinates.tsMs) : null;
    if (currentFixAvailable && freshestCoordinates) {
        const metrics = {
            latitude: freshestCoordinates.latitude,
            longitude: freshestCoordinates.longitude,
            speed_knots: freshRmc?.speedKnots ?? null,
            satellites: freshGga?.satellites ?? null,
            hdop: freshGga?.hdop ?? freshGsa?.hdop ?? null,
            altitude_meters: freshGga?.altitudeMeters ?? null,
            fix_status: fixStatus,
            fix_quality: deriveFixQuality(fixStatus, freshGga?.satellites ?? null, freshGga?.hdop ?? freshGsa?.hdop ?? null, "fixed"),
            position_source: freshestCoordinates.source,
            fix_age_ms: currentFixAgeMs,
        };
        return {
            timestamp: freshestCoordinates.timestamp,
            tsMs: freshestCoordinates.tsMs,
            signalState: "fixed",
            stale: false,
            metrics,
            fixDetails: {
                signal_state: "fixed",
                fix_quality: metrics.fix_quality,
                position_source: freshestCoordinates.source,
                stale: false,
                last_sentence_at: newestSentenceTimestamp([freshRmc, freshGga, freshGsa]),
                last_fix_at: freshestCoordinates.timestamp,
                last_valid_fix_at: freshestCoordinates.timestamp,
                fix_age_ms: currentFixAgeMs,
                satellites: metrics.satellites,
                hdop: metrics.hdop,
                altitude_meters: metrics.altitude_meters,
            },
        };
    }
    if (fixState.lastGoodFix && now - fixState.lastGoodFix.tsMs <= STALE_FIX_MAX_AGE_MS) {
        const staleFixAgeMs = now - fixState.lastGoodFix.tsMs;
        const metrics = {
            ...fixState.lastGoodFix.metrics,
            satellites: freshGga?.satellites ?? fixState.lastGoodFix.metrics.satellites ?? null,
            hdop: freshGga?.hdop ?? freshGsa?.hdop ?? fixState.lastGoodFix.metrics.hdop ?? null,
            altitude_meters: freshGga?.altitudeMeters ?? fixState.lastGoodFix.metrics.altitude_meters ?? null,
            fix_status: "stale",
            fix_quality: "stale",
            position_source: "last_known",
            fix_age_ms: staleFixAgeMs,
        };
        return {
            timestamp: fixState.lastGoodFix.timestamp,
            tsMs: fixState.lastGoodFix.tsMs,
            signalState: "stale",
            stale: true,
            metrics,
            fixDetails: {
                signal_state: "stale",
                fix_quality: "stale",
                position_source: "last_known",
                stale: true,
                last_sentence_at: newestSentenceTimestamp([freshRmc, freshGga, freshGsa]),
                last_fix_at: fixState.lastGoodFix.timestamp,
                last_valid_fix_at: fixState.lastGoodFix.timestamp,
                fix_age_ms: staleFixAgeMs,
                satellites: metrics.satellites,
                hdop: metrics.hdop,
                altitude_meters: metrics.altitude_meters,
            },
        };
    }
    return {
        timestamp: new Date(now).toISOString(),
        tsMs: now,
        signalState: "searching",
        stale: false,
        metrics: {
            fix_status: "searching",
            fix_quality: "searching",
            position_source: "none",
            satellites: freshGga?.satellites ?? null,
            hdop: freshGga?.hdop ?? freshGsa?.hdop ?? null,
            altitude_meters: freshGga?.altitudeMeters ?? null,
            fix_age_ms: null,
        },
        fixDetails: {
            signal_state: "searching",
            fix_quality: "searching",
            position_source: "none",
            stale: false,
            last_sentence_at: newestSentenceTimestamp([freshRmc, freshGga, freshGsa]),
            last_fix_at: fixState.lastGoodFix?.timestamp ?? null,
            last_valid_fix_at: fixState.lastGoodFix?.timestamp ?? null,
            fix_age_ms: fixState.lastGoodFix ? now - fixState.lastGoodFix.tsMs : null,
            satellites: freshGga?.satellites ?? null,
            hdop: freshGga?.hdop ?? freshGsa?.hdop ?? null,
            altitude_meters: freshGga?.altitudeMeters ?? null,
        },
    };
}
export function applyParsedSentenceToFixState(fixState, parsed, now = Date.now()) {
    const nextFixState = {
        ...fixState,
        rmc: fixState.rmc ? { ...fixState.rmc } : null,
        gga: fixState.gga ? { ...fixState.gga } : null,
        gsa: fixState.gsa ? { ...fixState.gsa } : null,
        lastGoodFix: fixState.lastGoodFix
            ? {
                ...fixState.lastGoodFix,
                metrics: { ...fixState.lastGoodFix.metrics },
                fixDetails: { ...fixState.lastGoodFix.fixDetails },
            }
            : null,
    };
    if (parsed.sentenceId === "RMC") {
        nextFixState.rmc = parseRmcSentence(parsed);
    }
    else if (parsed.sentenceId === "GGA") {
        nextFixState.gga = parseGgaSentence(parsed);
    }
    else if (parsed.sentenceId === "GSA") {
        nextFixState.gsa = parseGsaSentence(parsed, now);
    }
    else {
        return { fixState: nextFixState, snapshot: null };
    }
    const snapshot = createMergedFixSnapshot(nextFixState, now);
    if (snapshot.signalState === "fixed") {
        nextFixState.lastGoodFix = {
            ...snapshot,
            metrics: { ...snapshot.metrics },
            fixDetails: { ...snapshot.fixDetails },
        };
    }
    nextFixState.signalState = snapshot.signalState;
    nextFixState.fixStatus = snapshot.metrics.fix_status;
    nextFixState.fixQuality = snapshot.metrics.fix_quality;
    return { fixState: nextFixState, snapshot };
}
export function processNmeaSentence(fixState, sentence, now = Date.now()) {
    const parsed = nmea.parseNmeaSentence(sentence);
    return applyParsedSentenceToFixState(fixState, parsed, now);
}
