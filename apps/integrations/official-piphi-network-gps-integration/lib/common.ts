import crypto from "node:crypto";

import { client } from "./mqttclient.js";
import {
  clearRuntimeError,
  getActiveConfig,
  getRuntimeContext,
  noteTelemetry,
  type RuntimeEvent,
  recordRuntimeEvent,
  setRuntimeError,
  setRuntimeStatus,
} from "./runtime.js";

interface TelemetryPublisherClient {
  connected: boolean;
  publish(topic: string, payload: string, callback?: (error?: Error | null) => void): unknown;
}

let telemetryPublisherClient: TelemetryPublisherClient = client;

function getTelemetryEndpoint(): string | null {
  return process.env.PIPHI_TELEMETRY_ENDPOINT || process.env.PIPHI_CORE_TELEMETRY_URL || null;
}

function getEventsEndpoint(): string | null {
  return process.env.PIPHI_EVENTS_ENDPOINT || null;
}

function getContainerIdFromEnv(): string | null {
  return process.env.PIPHI_CONTAINER_ID || null;
}

function getInternalTokenFromEnv(): string | null {
  return process.env.PIPHI_INTEGRATION_INTERNAL_TOKEN || null;
}

export async function sign_payload(payload: unknown, secret?: string): Promise<string> {
  const data = JSON.stringify(payload, null, 2);
  if (secret) {
    return crypto.createHmac("sha256", secret).update(data).digest("hex");
  }
  return crypto.createHash("sha256").update(data).digest("hex");
}

async function postJson(
  url: string,
  payload: unknown,
  headers: Record<string, string> = {},
): Promise<void> {
  const response = await fetch(url, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      ...headers,
    },
    body: JSON.stringify(payload),
  });
  if (!response.ok) {
    throw new Error(`HTTP ${response.status}`);
  }
}

async function publishTelemetryViaMqtt(payload: Record<string, unknown>): Promise<void> {
  if (!telemetryPublisherClient.connected) {
    throw new Error("MQTT client is not connected");
  }

  await new Promise<void>((resolve, reject) => {
    telemetryPublisherClient.publish("piphi/telemetry", JSON.stringify(payload), (error) => {
      if (error) {
        reject(error);
        return;
      }
      resolve();
    });
  });
}

export async function send_telemetry(
  payload: Record<string, unknown> & {
    config_id?: string;
    device_id: string;
    integration_id?: string | null;
    timestamp: string;
    metrics: Record<string, unknown>;
    units?: Record<string, string>;
    container_id?: string | null;
  },
): Promise<{ delivered: true; delivery: string }> {
  let delivery = "mqtt";
  try {
    try {
      await publishTelemetryViaMqtt(payload);
    } catch (mqttError) {
      const telemetryEndpoint = getTelemetryEndpoint();
      const containerIdFromEnv = getContainerIdFromEnv();
      const internalTokenFromEnv = getInternalTokenFromEnv();
      if (telemetryEndpoint && (payload.container_id || containerIdFromEnv)) {
        await postJson(
          telemetryEndpoint,
          {
            config_id: payload.config_id,
            device_id: payload.device_id,
            timestamp: payload.timestamp,
            metrics: payload.metrics,
            units: payload.units || undefined,
          },
          {
            "X-Container-Id": String(payload.container_id || containerIdFromEnv),
            ...(internalTokenFromEnv
              ? { "X-PiPhi-Integration-Token": internalTokenFromEnv }
              : {}),
          },
        );
        recordRuntimeEvent({
          type: "telemetry_http_fallback",
          severity: "warning",
          device_id: payload.device_id,
          data: {
            message: mqttError instanceof Error ? mqttError.message : String(mqttError),
          },
        });
        delivery = "rest_fallback";
      } else {
        throw mqttError;
      }
    }
    clearRuntimeError();
  } catch (error) {
    setRuntimeError(error);
    recordRuntimeEvent({
      type: "telemetry_delivery_failed",
      severity: "error",
      device_id: payload.device_id,
      data: { message: error instanceof Error ? error.message : String(error) },
    });
    delivery = "mqtt_error";
  }

  noteTelemetry(payload, delivery);
  setRuntimeStatus("streaming");
  return { delivered: true, delivery };
}

export async function emit_event(eventPayload: {
  type: string;
  severity?: string;
  device_id?: string | null;
  data?: Record<string, unknown>;
}): Promise<RuntimeEvent> {
  const event = recordRuntimeEvent(eventPayload);
  const eventsEndpoint = getEventsEndpoint();
  const activeConfig = eventPayload.device_id ? getActiveConfig(eventPayload.device_id) : null;
  if (eventsEndpoint && activeConfig?.integrationId && activeConfig.containerId) {
    try {
      const runtime = getRuntimeContext();
      const containerId = activeConfig.containerId || runtime.auth.containerId;
      await postJson(
        eventsEndpoint,
        {
          event_id: event.event_id,
          type: event.type,
          ts: event.ts,
          integration_id: activeConfig.integrationId,
          config_id: activeConfig.configId,
          container_id: containerId,
          device_id: event.device_id,
          severity: event.severity,
          transport: "rest",
          data: event.data,
        },
        {
          "X-Container-Id": String(containerId),
          ...(runtime.auth.internalToken
            ? { "X-PiPhi-Integration-Token": runtime.auth.internalToken }
            : {}),
        },
      );
    } catch (error) {
      setRuntimeError(error);
    }
  }
  return event;
}

export function handle_runtime_error(error: unknown): void {
  setRuntimeError(error);
  recordRuntimeEvent({
    type: "runtime_error",
    severity: "error",
    data: {
      message: error instanceof Error ? error.message : String(error),
    },
  });
}

export function setTelemetryPublisherClientForTests(
  nextClient: TelemetryPublisherClient | null,
): void {
  telemetryPublisherClient = nextClient ?? client;
}
