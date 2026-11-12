import { ReadlineParser, SerialPort } from "serialport";

import { logger } from "../server.js";
import { emit_event, handle_runtime_error, send_telemetry, sign_payload } from "./common.js";
import {
  applyParsedSentenceToFixState,
  buildUnits,
  createInitialFixState,
  createMergedFixSnapshot,
  processNmeaSentence,
  type FixMetrics,
  type FixState,
  type MergedFixSnapshot,
} from "./gps-fix.js";
import {
  type FixDetails,
  getActiveConfigs,
  getRuntimeSnapshot,
  removeActiveConfig,
  setRuntimeStatus,
  updateDeviceRuntime,
  upsertActiveConfig,
} from "./runtime.js";

const LIKELY_SERIAL_PATH_PATTERN =
  /(tty(USB|ACM|AMA)\d+|rfcomm\d+|cu\.(usb|SLAB_USB|usbserial|wchusbserial)|tty\.usb)/i;
const EXACT_GPS_DEVICE_MATCHES: Record<string, string> = {
  "1546:01a7": "VK162 USB GPS",
  "1546:01a8": "VK172 USB GPS",
};
const GPS_VENDOR_HINTS = [
  "gps",
  "gnss",
  "u-blox",
  "ublox",
  "globalsat",
  "vk162",
  "vk172",
  "bu-353",
  "navigation",
];
const SERIAL_BRIDGE_HINTS: Record<string, string> = {
  "067b:2303": "Prolific USB-serial adapter",
  "10c4:ea60": "Silicon Labs CP210x adapter",
  "0403:6001": "FTDI USB-serial adapter",
  "1a86:7523": "WCH CH340 adapter",
};

interface GPSDiscoveryDevice extends Record<string, unknown> {
  id: string;
  path: string;
  name: string;
  manufacturer: string | null;
  product: string | null;
  vendorId: string | null;
  productId: string | null;
  serialNumber: string | null;
  locationId: string | null;
  hwid: string;
  confidence: string;
  score: number;
  likely_gps: boolean;
  detected_as: string | null;
  driver_family: string | null;
  detection_reasons: string[];
}

type ListedPort = Awaited<ReturnType<typeof SerialPort.list>>[number];

interface GPSConfig {
  id?: string;
  config_id?: string;
  device_id?: string;
  integration_id?: string;
  path: string;
  container_id?: string | null;
  configName?: string;
  secret?: string;
}

interface GPSContext {
  configId: string;
  deviceId: string;
  containerId: string | null;
  integrationId: string | null;
  configName: string;
  signature: string | null;
}

interface GPSRefreshResult {
  success: boolean;
  message?: string;
  path?: string;
  is_open?: boolean;
}

interface GPSTestHooks {
  getGPSDevicePaths?: () => Promise<GPSDiscoveryDevice[]>;
  refreshGPSDevice?: (
    target: { path?: string },
  ) => Promise<GPSRefreshResult>;
}

let gpsTestHooks: GPSTestHooks | null = null;

function safeString(value: unknown): string {
  return typeof value === "string" ? value : "";
}

function sanitizeVidPid(value: unknown): string {
  return safeString(value).trim().toLowerCase();
}

function getVidPid(port: ListedPort): string | null {
  const vendorId = sanitizeVidPid(port.vendorId);
  const productId = sanitizeVidPid(port.productId);
  if (!vendorId || !productId) {
    return null;
  }
  return `${vendorId}:${productId}`;
}

function getHwidString(port: ListedPort): string {
  let hwid = `USB VID:PID=${port.vendorId ?? "????"}:${port.productId ?? "????"}`;
  if (port.serialNumber) hwid += ` SER=${port.serialNumber}`;
  if (port.locationId) hwid += ` LOCATION=${port.locationId}`;
  return hwid;
}

function classifyDeviceConfidence(score: number): string {
  if (score >= 100) return "confirmed";
  if (score >= 50) return "likely";
  if (score >= 10) return "possible";
  return "unknown";
}

function scoreGPSPort(port: ListedPort): GPSDiscoveryDevice {
  const path = safeString(port.path);
  const manufacturer = safeString(port.manufacturer);
  const product = safeString((port as ListedPort & { product?: unknown }).product);
  const serialNumber = safeString(port.serialNumber);
  const locationId = safeString(port.locationId);
  const vidPid = getVidPid(port);
  const haystack = [path, manufacturer, product, serialNumber, locationId, getHwidString(port)]
    .join(" ")
    .toLowerCase();
  const reasons: string[] = [];
  let score = 0;
  let detectedAs: string | null = null;

  if (vidPid && EXACT_GPS_DEVICE_MATCHES[vidPid]) {
    score += 100;
    detectedAs = EXACT_GPS_DEVICE_MATCHES[vidPid];
    reasons.push(`known_gps_vid_pid:${vidPid}`);
  }

  if (vidPid && SERIAL_BRIDGE_HINTS[vidPid]) {
    score += 15;
    reasons.push(`usb_serial_bridge:${SERIAL_BRIDGE_HINTS[vidPid]}`);
  }

  if (vidPid && vidPid.startsWith("1546:")) {
    score += 25;
    reasons.push("ublox_vendor_family");
  }

  const matchedHints = GPS_VENDOR_HINTS.filter((hint) => haystack.includes(hint));
  if (matchedHints.length > 0) {
    score += 50;
    reasons.push(`gps_keywords:${matchedHints.join(",")}`);
    if (!detectedAs) {
      detectedAs = matchedHints[0] ?? null;
    }
  }

  if (LIKELY_SERIAL_PATH_PATTERN.test(path)) {
    score += 10;
    reasons.push("serial_path_pattern");
  }

  const confidence = classifyDeviceConfidence(score);
  const likelyGps = confidence !== "unknown";
  const driverFamily = vidPid && SERIAL_BRIDGE_HINTS[vidPid] ? SERIAL_BRIDGE_HINTS[vidPid] : null;
  const displayName = detectedAs
    ? `${path} (${detectedAs})`
    : product || manufacturer
      ? `${path} (${product || manufacturer})`
      : path;

  return {
    id: path,
    path,
    name: displayName,
    manufacturer: manufacturer || null,
    product: product || null,
    vendorId: sanitizeVidPid(port.vendorId) || null,
    productId: sanitizeVidPid(port.productId) || null,
    serialNumber: serialNumber || null,
    locationId: locationId || null,
    hwid: getHwidString(port),
    confidence,
    score,
    likely_gps: likelyGps,
    detected_as: detectedAs,
    driver_family: driverFamily,
    detection_reasons: reasons,
  };
}

async function listCandidateGPSDevices(): Promise<GPSDiscoveryDevice[]> {
  const ports = await SerialPort.list();
  return ports
    .map(scoreGPSPort)
    .filter((port) => port.path && (port.score >= 10 || LIKELY_SERIAL_PATH_PATTERN.test(port.path)))
    .sort((left, right) => right.score - left.score || left.path.localeCompare(right.path));
}

async function getGPSDeviceInfo(path: string): Promise<GPSDiscoveryDevice | null> {
  const devices = await listCandidateGPSDevices();
  return devices.find((device) => device.path === path) || null;
}

export async function initializeClient(serialPort: string): Promise<GPS> {
  const existingClient = GPS.gpsSerialPortMap[serialPort];
  if (existingClient) {
    return existingClient;
  }
  return new GPS(serialPort);
}

export async function getGPSerialPort(serialPort: string): Promise<GPS | undefined> {
  return GPS.gpsSerialPortMap[serialPort];
}

export async function getGPSDevicePaths(): Promise<GPSDiscoveryDevice[]> {
  if (gpsTestHooks?.getGPSDevicePaths) {
    return gpsTestHooks.getGPSDevicePaths();
  }
  return listCandidateGPSDevices();
}

export function getEntitiesPayload(): { entities: Array<Record<string, unknown>> } {
  const activeConfigs = getActiveConfigs();
  const entities = activeConfigs.flatMap((config) => [
    { id: `${config.deviceId}.latitude`, device_id: config.deviceId, name: `${config.configName} Latitude`, capabilities: ["latitude"] },
    { id: `${config.deviceId}.longitude`, device_id: config.deviceId, name: `${config.configName} Longitude`, capabilities: ["longitude"] },
    { id: `${config.deviceId}.satellites`, device_id: config.deviceId, name: `${config.configName} Satellites`, capabilities: ["satellites"] },
    { id: `${config.deviceId}.speed_knots`, device_id: config.deviceId, name: `${config.configName} Speed`, capabilities: ["speed_knots"] },
    { id: `${config.deviceId}.fix_status`, device_id: config.deviceId, name: `${config.configName} Fix Status`, capabilities: ["fix_status"] },
    { id: `${config.deviceId}.fix_quality`, device_id: config.deviceId, name: `${config.configName} Fix Quality`, capabilities: ["fix_quality"] },
    { id: `${config.deviceId}.hdop`, device_id: config.deviceId, name: `${config.configName} HDOP`, capabilities: ["hdop"] },
  ]);
  return { entities };
}

export function getStatePayload(): Record<string, unknown> {
  const snapshot = getRuntimeSnapshot() as {
    status: string;
    devices: Record<string, unknown>;
    activeConfigs: Record<string, unknown>;
    telemetry: Record<string, unknown>;
  };
  return {
    status: snapshot.status,
    devices: snapshot.devices,
    active_configs: Object.values(snapshot.activeConfigs),
    telemetry: snapshot.telemetry,
  };
}

export function getDiagnosticsPayload(): Record<string, unknown> {
  return getRuntimeSnapshot();
}

export async function configureGPSDevice(config: Record<string, unknown>): Promise<Record<string, unknown>> {
  const path = typeof config.path === "string" ? config.path : "";
  if (!path) {
    throw new Error("A device path is required to configure the GPS integration");
  }
  const gps = await initializeClient(path);
  return gps.configure(config as unknown as GPSConfig);
}

export async function deconfigureGPSDevice(
  config: { path?: string; id?: string; config?: { path?: string; id?: string } } = {},
): Promise<{ success: true; removed: number }> {
  const configPath = config.path || config.config?.path;
  const deviceId = config.id || config.config?.id || configPath;

  if (!configPath) {
    const configuredPaths = Object.keys(GPS.gpsSerialPortMap);
    await Promise.all(configuredPaths.map((path) => GPS.gpsSerialPortMap[path]?.deconfigure()));
    return { success: true, removed: configuredPaths.length };
  }

  const gps = GPS.gpsSerialPortMap[configPath];
  if (!gps) {
    if (deviceId) {
      removeActiveConfig(deviceId);
    }
    return { success: true, removed: 0 };
  }
  await gps.deconfigure();
  return { success: true, removed: 1 };
}

export async function refreshGPSDevice(
  target: { path?: string } = {},
): Promise<GPSRefreshResult> {
  if (gpsTestHooks?.refreshGPSDevice) {
    return gpsTestHooks.refreshGPSDevice(target);
  }
  const gps = target.path
    ? GPS.gpsSerialPortMap[target.path]
    : Object.values(GPS.gpsSerialPortMap)[0];
  if (!gps) {
    return { success: false, message: "No configured GPS device found" };
  }
  await gps.openSerialPort();
  await gps.refreshRuntimeState();
  return { success: true, path: gps.path, is_open: gps.serialPort.isOpen };
}

export function setGPSTestHooksForTests(hooks: GPSTestHooks | null): void {
  gpsTestHooks = hooks;
}

export class GPS {
  static gpsSerialPortMap: Record<string, GPS> = {};

  path: string;
  context: GPSContext;
  discoveryMetadata: GPSDiscoveryDevice | null;
  serialPort: SerialPort;
  parser: ReadlineParser;
  dataStream: unknown;
  onData: ((nmeaSentence: string) => Promise<void>) | null;
  fixState: FixState;
  lastTransitionState: string;

  constructor(serialPort: string) {
    if (!serialPort) {
      throw new Error("No serial port specified");
    }

    try {
      this.path = serialPort;
      this.context = {
        configId: serialPort,
        deviceId: serialPort,
        containerId: null,
        integrationId: null,
        configName: serialPort,
        signature: null,
      };
      this.discoveryMetadata = null;
      this.serialPort = new SerialPort({
        path: serialPort,
        baudRate: 57600,
        autoOpen: false,
      });
      this.dataStream = null;
      GPS.gpsSerialPortMap[serialPort] = this;
      this.parser = this.serialPort.pipe(new ReadlineParser({ delimiter: "\n" }));
      this.onData = null;
      this.fixState = createInitialFixState();
      this.lastTransitionState = "idle";

      this.serialPort.on("error", async (error: Error) => {
        handle_runtime_error(error);
        updateDeviceRuntime(this.context.deviceId, {
          path: this.path,
          connected: false,
          fix_status: "error",
          discovery: this.discoveryMetadata,
          fix_details: {
            signal_state: "error",
            fix_quality: "error",
            position_source: "none",
          },
        });
        await emit_event({
          type: "gps_serial_error",
          severity: "error",
          device_id: this.context.deviceId,
          data: { path: this.path, message: error.message },
        });
      });
    } catch (error) {
      handle_runtime_error(error);
      throw error;
    }
  }

  getMergedFixSnapshot(): MergedFixSnapshot {
    return createMergedFixSnapshot(this.fixState);
  }

  async refreshRuntimeState(snapshot = this.getMergedFixSnapshot()): Promise<void> {
    const runtimePatch: Record<string, unknown> = {
      path: this.path,
      connected: this.serialPort.isOpen,
      fix_status: snapshot.metrics.fix_status,
      discovery: this.discoveryMetadata,
      fix_details: snapshot.fixDetails,
    };
    if (snapshot.signalState === "fixed" || snapshot.signalState === "stale") {
      runtimePatch.lastMetrics = snapshot.metrics;
    }
    updateDeviceRuntime(this.context.deviceId, runtimePatch);
  }

  async openSerialPort(): Promise<void> {
    if (!this.serialPort.isOpen) {
      await new Promise<void>((resolve, reject) => {
        this.serialPort.open((error) => {
          if (error) {
            reject(error);
            return;
          }
          resolve();
        });
      });
      await this.refreshRuntimeState();
      await emit_event({
        type: "gps_serial_connected",
        device_id: this.context.deviceId,
        data: { path: this.path, discovery: this.discoveryMetadata },
      });
    }
  }

  async closeSerialPort(): Promise<void> {
    if (this.onData) {
      this.parser.off("data", this.onData);
      this.onData = null;
    }
    if (this.serialPort.isOpen) {
      await new Promise<void>((resolve, reject) => {
        this.serialPort.close((error) => {
          if (error) {
            reject(error);
            return;
          }
          resolve();
        });
      });
    }
    updateDeviceRuntime(this.context.deviceId, {
      path: this.path,
      connected: false,
      fix_status: "stopped",
      discovery: this.discoveryMetadata,
      fix_details: {
        signal_state: "stopped",
        fix_quality: this.fixState.fixQuality,
        position_source: this.fixState.lastGoodFix ? "last_known" : "none",
      },
    });
  }

  async configure(config: GPSConfig): Promise<Record<string, unknown>> {
    const previousDeviceId = this.context.deviceId;
    this.discoveryMetadata = await getGPSDeviceInfo(config.path);
    this.context = {
      configId: config.config_id || config.id || config.path,
      deviceId: config.device_id || config.path,
      containerId: config.container_id || null,
      integrationId: config.integration_id || null,
      configName: config.configName || config.path,
      signature: await sign_payload({ id: config.id || config.path, path: config.path }, config.secret),
    };
    if (previousDeviceId && previousDeviceId !== this.context.deviceId) {
      removeActiveConfig(previousDeviceId);
    }
    upsertActiveConfig({
      configId: this.context.configId,
      deviceId: this.context.deviceId,
      path: config.path,
      containerId: this.context.containerId,
      integrationId: this.context.integrationId,
      configName: this.context.configName,
    });
    updateDeviceRuntime(this.context.deviceId, {
      path: config.path,
      discovery: this.discoveryMetadata,
    });
    setRuntimeStatus("configured");
    await this.openSerialPort();
    await this.getRealTimeData(this.context.signature);
    await emit_event({
      type: "gps_configured",
      device_id: this.context.deviceId,
      data: {
        path: config.path,
        container_id: this.context.containerId,
        discovery: this.discoveryMetadata,
      },
    });
    return {
      success: true,
      device_id: this.context.deviceId,
      path: config.path,
      message: "GPS device configured successfully",
      device: this.discoveryMetadata,
    };
  }

  async deconfigure(): Promise<void> {
    await this.closeSerialPort();
    removeActiveConfig(this.context.deviceId);
    delete GPS.gpsSerialPortMap[this.path];
    await emit_event({
      type: "gps_deconfigured",
      device_id: this.context.deviceId,
      data: { path: this.path },
    });
    if (Object.keys(GPS.gpsSerialPortMap).length === 0) {
      setRuntimeStatus("idle");
    }
  }

  async emitTelemetry(metrics: FixMetrics, timestamp: string): Promise<void> {
    const telemetryPayload = {
      config_id: this.context.configId,
      device_id: this.context.deviceId,
      container_id: this.context.containerId,
      integration_id: this.context.integrationId,
      timestamp,
      metrics,
      units: buildUnits(metrics),
      signature: this.context.signature,
    };
    await send_telemetry(telemetryPayload);
    updateDeviceRuntime(this.context.deviceId, {
      path: this.path,
      connected: true,
      fix_status: String(metrics.fix_status ?? this.fixState.fixStatus),
      discovery: this.discoveryMetadata,
      lastMetrics: metrics,
      fix_details: {
        signal_state: metrics.fix_status === "stale" ? "stale" : "fixed",
        fix_quality: String(metrics.fix_quality ?? "unknown"),
        position_source: String(metrics.position_source ?? "none"),
        stale: metrics.fix_status === "stale",
        last_fix_at: timestamp,
        last_valid_fix_at:
          metrics.fix_status === "stale"
            ? this.fixState.lastGoodFix?.timestamp ?? timestamp
            : timestamp,
        fix_age_ms: typeof metrics.fix_age_ms === "number" ? metrics.fix_age_ms : null,
        satellites: typeof metrics.satellites === "number" ? metrics.satellites : null,
        hdop: typeof metrics.hdop === "number" ? metrics.hdop : null,
        altitude_meters:
          typeof metrics.altitude_meters === "number" ? metrics.altitude_meters : null,
      },
    });
  }

  async handleSignalTransition(snapshot: MergedFixSnapshot): Promise<void> {
    if (snapshot.signalState === this.lastTransitionState) {
      return;
    }
    this.lastTransitionState = snapshot.signalState;
    const eventType =
      snapshot.signalState === "fixed"
        ? "gps_fix_acquired"
        : snapshot.signalState === "stale"
          ? "gps_fix_stale"
          : "gps_searching";

    await emit_event({
      type: eventType,
      device_id: this.context.deviceId,
      data: {
        path: this.path,
        fix_status: snapshot.metrics.fix_status,
        fix_quality: snapshot.metrics.fix_quality,
        position_source: snapshot.metrics.position_source,
        latitude: snapshot.metrics.latitude ?? null,
        longitude: snapshot.metrics.longitude ?? null,
        satellites: snapshot.metrics.satellites ?? null,
        hdop: snapshot.metrics.hdop ?? null,
        fix_age_ms: snapshot.metrics.fix_age_ms ?? null,
      },
    });
  }

  async publishFixSnapshot(snapshot: MergedFixSnapshot): Promise<void> {
    const previousSignalState = this.lastTransitionState;
    await this.refreshRuntimeState(snapshot);
    await this.handleSignalTransition(snapshot);
    if (snapshot.signalState === "fixed") {
      logger.info(
        `Coordinates found latitude: ${snapshot.metrics.latitude} longitude: ${snapshot.metrics.longitude} sending telemetry packet`,
      );
      await this.emitTelemetry(snapshot.metrics, snapshot.timestamp);
      return;
    }
    if (snapshot.signalState === "stale" && previousSignalState !== "stale") {
      await this.emitTelemetry(snapshot.metrics, snapshot.timestamp);
    }
  }

  async handleParsedSentence(parsed: unknown): Promise<void> {
    const result = applyParsedSentenceToFixState(this.fixState, parsed as never);
    if (!result.snapshot) {
      return;
    }
    this.fixState = result.fixState;
    await this.publishFixSnapshot(result.snapshot);
  }

  async getRealTimeData(signature: string | null): Promise<void> {
    if (this.onData) {
      this.parser.off("data", this.onData);
    }
    this.context.signature = signature;
    this.onData = async (nmeaSentence: string) => {
      try {
        const result = processNmeaSentence(this.fixState, nmeaSentence);
        if (!result.snapshot) {
          return;
        }
        this.fixState = result.fixState;
        await this.publishFixSnapshot(result.snapshot);
      } catch (error) {
        if (error instanceof Error && error.message.includes("No known parser for sentence ID")) {
          return;
        }
        handle_runtime_error(error);
      }
    };
    this.parser.on("data", this.onData);
  }
}
