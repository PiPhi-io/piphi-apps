import type { RuntimeConfig } from "piphi-runtime-kit-node";

export const ZWAVE_EVENT_SCHEMA = "piphi.zwave.event.v1";

export type DriverLifecycle = "stopped" | "starting" | "ready" | "degraded" | "stopping";

export type DeviceState = {
  connected: boolean;
  driver_ready: boolean;
  controller_ready: boolean;
  controller_path_suffix: string;
  lifecycle: DriverLifecycle;
  node_count: number;
  ready_node_count: number;
  sleeping_node_count: number;
  dead_node_count: number;
  event_sequence: number;
  event_queue_depth: number;
  dropped_event_count: number;
  command_queue_depth: number;
  command_queue_capacity: number;
  last_event_at?: string | null;
  last_error_code?: string | null;
  alias?: string | null;
};

export interface DeviceConfig extends RuntimeConfig {
  controller_path: string;
  alias?: string | null;
  event_queue_capacity?: number | null;
  command_queue_capacity?: number | null;
}

export type DeviceEntry = {
  configId: string;
  deviceId: string;
  containerId?: string | null;
  integrationId?: string | null;
  controllerPath: string;
  alias?: string | null;
  config: DeviceConfig;
  latestState?: DeviceState;
};

export type ZWaveTransportEvent = {
  schema_version: typeof ZWAVE_EVENT_SCHEMA;
  sequence: number;
  occurred_at: string;
  event_type: string;
  source: "zwave-js";
  node_id?: number;
  endpoint?: number;
  command_class?: number;
  value_id?: {
    command_class: number;
    endpoint: number;
    property: string | number;
    property_key?: string | number;
    property_name?: string;
    property_key_name?: string;
  };
  payload: Record<string, unknown>;
};

export type DriverSnapshot = {
  lifecycle: DriverLifecycle;
  driverReady: boolean;
  controllerReady: boolean;
  controllerPathSuffix: string;
  driverVersion: string;
  homeIdSuffix?: string;
  controllerNodeId?: number;
  nodeCount: number;
  readyNodeCount: number;
  sleepingNodeCount: number;
  deadNodeCount: number;
  reconnectCount: number;
  lastEventAt?: string;
  lastErrorCode?: string;
};

export type DriverCommand =
  | { name: "refresh_controller_information" }
  | { name: "reconnect_driver" }
  | { name: "ping_node"; nodeId: number }
  | { name: "request_node_interview"; nodeId: number }
  | { name: "refresh_node_values"; nodeId: number };

export interface DriverSession {
  start(): Promise<void>;
  stop(): Promise<void>;
  execute(command: DriverCommand): Promise<Record<string, unknown>>;
  snapshot(): DriverSnapshot;
}

export type DriverSessionFactory = (options: {
  config: DeviceConfig;
  onEvent: (event: Omit<ZWaveTransportEvent, "sequence">) => void;
}) => DriverSession;
