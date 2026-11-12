import mqtt, { type MqttClient } from "mqtt";

import { logger } from "../server.js";
import { recordRuntimeEvent, setMqttStatus } from "./runtime.js";

const protocol = process.env.MQTT_PROTOCOL || "mqtt";
const host = process.env.MQTT_HOST || "localhost";
const port = process.env.MQTT_PORT || "1883";
const clientId = `mqtt_${Math.random().toString(16).slice(3)}`;
const connectUrl = `${protocol}://${host}:${port}`;

function createTestClient(): MqttClient {
  const fakeClient = {
    connected: false,
    publish(_topic: string, _payload: string, callback?: (error?: Error | null) => void) {
      callback?.(null);
      return true;
    },
    on() {
      return fakeClient as unknown as MqttClient;
    },
  };
  return fakeClient as unknown as MqttClient;
}

const shouldDisableMqtt = process.env.NODE_ENV === "test" || process.env.PIPHI_DISABLE_MQTT === "true";

export const client: MqttClient = shouldDisableMqtt
  ? createTestClient()
  : mqtt.connect(connectUrl, {
      clientId,
      clean: true,
      connectTimeout: 4000,
      reconnectPeriod: 1000,
    });

client.on("connect", () => {
  setMqttStatus(true);
  recordRuntimeEvent({ type: "mqtt_connected", data: { host, port } });
  logger.info("Connected to MQTT broker");
});

client.on("reconnect", () => {
  setMqttStatus(false);
  recordRuntimeEvent({ type: "mqtt_reconnecting", severity: "warning", data: { host, port } });
});

client.on("error", (error: Error) => {
  setMqttStatus(false);
  recordRuntimeEvent({
    type: "mqtt_error",
    severity: "error",
    data: { message: error.message },
  });
});

client.on("close", () => {
  setMqttStatus(false);
  recordRuntimeEvent({ type: "mqtt_closed", severity: "warning", data: { host, port } });
});
