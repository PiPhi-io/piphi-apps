import nmea from "nmea-simple";

export const CURRENT_FIX_MAX_AGE_MS = 15000;
export const STALE_FIX_MAX_AGE_MS = 180000;

type NullableNumber = number | null;

export interface SentenceSnapshotBase {
  source: string;
  timestamp: string;
  tsMs: number;
}

export interface RmcSnapshot extends SentenceSnapshotBase {
  source: "rmc";
  latitude: NullableNumber;
  longitude: NullableNumber;
  speedKnots: NullableNumber;
  status: string;
}

export interface GgaSnapshot extends SentenceSnapshotBase {
  source: "gga";
  latitude: NullableNumber;
  longitude: NullableNumber;
  satellites: NullableNumber;
  hdop: NullableNumber;
  altitudeMeters: NullableNumber;
  fixType: string;
}

export interface GsaSnapshot extends SentenceSnapshotBase {
  source: "gsa";
  hdop: NullableNumber;
  pdop: NullableNumber;
  vdop: NullableNumber;
  fixType: string;
}

export interface FixMetrics extends Record<string, unknown> {
  latitude?: NullableNumber;
  longitude?: NullableNumber;
  speed_knots?: NullableNumber;
  satellites: NullableNumber;
  hdop: NullableNumber;
  altitude_meters: NullableNumber;
  fix_status: string;
  fix_quality: string;
  position_source: string;
  fix_age_ms: NullableNumber;
}

export interface FixDetails {
  signal_state: string;
  fix_quality: string;
  position_source: string;
  stale: boolean;
  last_sentence_at: string | null;
  last_fix_at: string | null;
  last_valid_fix_at: string | null;
  fix_age_ms: NullableNumber;
  satellites: NullableNumber;
  hdop: NullableNumber;
  altitude_meters: NullableNumber;
}

export interface MergedFixSnapshot {
  timestamp: string;
  tsMs: number;
  signalState: string;
  stale: boolean;
  metrics: FixMetrics;
  fixDetails: FixDetails;
}

export interface FixState {
  rmc: RmcSnapshot | null;
  gga: GgaSnapshot | null;
  gsa: GsaSnapshot | null;
  signalState: string;
  fixStatus: string;
  fixQuality: string;
  lastGoodFix: MergedFixSnapshot | null;
}

interface ParsedSentence {
  sentenceId?: string;
  datetime?: Date | string;
  time?: Date | string;
  latitude?: number;
  longitude?: number;
  speedKnots?: number;
  status?: string;
  satellitesInView?: number;
  horizontalDilution?: number;
  altitudeMeters?: number;
  fixType?: string;
  fixMode?: string;
  HDOP?: number;
  PDOP?: number;
  VDOP?: number;
}

function safeString(value: unknown): string {
  return typeof value === "string" ? value : "";
}

function normalizeNumber(value: unknown): NullableNumber {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

export function toIsoTimestamp(value: unknown): string {
  if (value instanceof Date && !Number.isNaN(value.getTime())) {
    return value.toISOString();
  }
  if (typeof value === "string" && value.length > 0) {
    if (/^\d{2}:\d{2}:\d{2}(\.\d+)?$/.test(value)) {
      const now = new Date();
      const [hours = "0", minutes = "0", secondsWithFraction = "0"] = value.split(":");
      const [seconds = "0", fraction = "0"] = secondsWithFraction.split(".");
      now.setUTCHours(
        Number(hours),
        Number(minutes),
        Number(seconds),
        Number(fraction.padEnd(3, "0").slice(0, 3)),
      );
      return now.toISOString();
    }
    return value;
  }
  return new Date().toISOString();
}

export function toTimestampMs(value: unknown): number {
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

function isFreshSnapshot(
  snapshot: SentenceSnapshotBase | null,
  now: number,
  maxAgeMs = CURRENT_FIX_MAX_AGE_MS,
): boolean {
  return Boolean(snapshot && typeof snapshot.tsMs === "number" && now - snapshot.tsMs <= maxAgeMs);
}

export function normalizeFixStatus(value: unknown): string {
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

export function deriveFixQuality(
  fixStatus: string,
  satellites: NullableNumber,
  hdop: NullableNumber,
  signalState: string,
): string {
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

export function buildUnits(metrics: Record<string, unknown>): Record<string, string> {
  const units: Record<string, string> = {};
  if (metrics.latitude != null) units.latitude = "degrees";
  if (metrics.longitude != null) units.longitude = "degrees";
  if (metrics.speed_knots != null) units.speed_knots = "kn";
  if (metrics.satellites != null) units.satellites = "count";
  if (metrics.hdop != null) units.hdop = "ratio";
  if (metrics.altitude_meters != null) units.altitude_meters = "m";
  if (metrics.fix_age_ms != null) units.fix_age_ms = "ms";
  return units;
}

export function parseRmcSentence(parsed: ParsedSentence): RmcSnapshot {
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

export function parseGgaSentence(parsed: ParsedSentence): GgaSnapshot {
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

export function parseGsaSentence(parsed: ParsedSentence, now = Date.now()): GsaSnapshot {
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

function newestSentenceTimestamp(
  sentences: Array<SentenceSnapshotBase | null>,
): string | null {
  const newest = sentences
    .filter((value): value is SentenceSnapshotBase => Boolean(value))
    .sort((left, right) => right.tsMs - left.tsMs)[0];
  return newest ? newest.timestamp : null;
}

export function createInitialFixState(): FixState {
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

export function createMergedFixSnapshot(fixState: FixState, now = Date.now()): MergedFixSnapshot {
  const freshRmc = isFreshSnapshot(fixState.rmc, now) ? fixState.rmc : null;
  const freshGga = isFreshSnapshot(fixState.gga, now) ? fixState.gga : null;
  const freshGsa = isFreshSnapshot(fixState.gsa, now) ? fixState.gsa : null;

  const coordinateCandidates = [freshRmc, freshGga]
    .filter(
      (candidate): candidate is RmcSnapshot | GgaSnapshot =>
        Boolean(candidate && candidate.latitude != null && candidate.longitude != null),
    )
    .sort((left, right) => right.tsMs - left.tsMs);

  const freshestCoordinates = coordinateCandidates[0] ?? null;

  const fixStatus =
    freshGga?.fixType && freshGga.fixType !== "searching"
      ? normalizeFixStatus(freshGga.fixType)
      : freshGsa?.fixType && freshGsa.fixType !== "searching"
        ? normalizeFixStatus(freshGsa.fixType)
        : freshRmc?.status === "valid"
          ? "valid"
          : "searching";

  const currentFixAvailable = Boolean(
    freshestCoordinates && (freshRmc?.status === "valid" || fixStatus !== "searching"),
  );
  const currentFixAgeMs = freshestCoordinates ? Math.max(0, now - freshestCoordinates.tsMs) : null;

  if (currentFixAvailable && freshestCoordinates) {
    const metrics: FixMetrics = {
      latitude: freshestCoordinates.latitude,
      longitude: freshestCoordinates.longitude,
      speed_knots: freshRmc?.speedKnots ?? null,
      satellites: freshGga?.satellites ?? null,
      hdop: freshGga?.hdop ?? freshGsa?.hdop ?? null,
      altitude_meters: freshGga?.altitudeMeters ?? null,
      fix_status: fixStatus,
      fix_quality: deriveFixQuality(
        fixStatus,
        freshGga?.satellites ?? null,
        freshGga?.hdop ?? freshGsa?.hdop ?? null,
        "fixed",
      ),
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
    const metrics: FixMetrics = {
      ...fixState.lastGoodFix.metrics,
      satellites: freshGga?.satellites ?? fixState.lastGoodFix.metrics.satellites ?? null,
      hdop: freshGga?.hdop ?? freshGsa?.hdop ?? fixState.lastGoodFix.metrics.hdop ?? null,
      altitude_meters:
        freshGga?.altitudeMeters ?? fixState.lastGoodFix.metrics.altitude_meters ?? null,
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

export function applyParsedSentenceToFixState(
  fixState: FixState,
  parsed: ParsedSentence,
  now = Date.now(),
): { fixState: FixState; snapshot: MergedFixSnapshot | null } {
  const nextFixState: FixState = {
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
  } else if (parsed.sentenceId === "GGA") {
    nextFixState.gga = parseGgaSentence(parsed);
  } else if (parsed.sentenceId === "GSA") {
    nextFixState.gsa = parseGsaSentence(parsed, now);
  } else {
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

export function processNmeaSentence(
  fixState: FixState,
  sentence: string,
  now = Date.now(),
): { fixState: FixState; snapshot: MergedFixSnapshot | null } {
  const parsed = nmea.parseNmeaSentence(sentence) as ParsedSentence;
  return applyParsedSentenceToFixState(fixState, parsed, now);
}
