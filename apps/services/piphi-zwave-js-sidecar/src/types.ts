import type { RuntimeConfig } from "piphi-runtime-kit-node";

export type DeviceState = {
  connected: boolean;
  host: string;
  alias?: string | null;
};

export interface DeviceConfig extends RuntimeConfig {
  host: string;
  alias?: string | null;
  api_key?: string | null;
  base_url?: string | null;
  poll_interval_seconds?: number | null;
  service_name?: string | null;
}

export type DeviceEntry = {
  configId: string;
  deviceId: string;
  containerId?: string | null;
  integrationId?: string | null;
  host: string;
  alias?: string | null;
  config: DeviceConfig;
  latestState?: DeviceState;
};
