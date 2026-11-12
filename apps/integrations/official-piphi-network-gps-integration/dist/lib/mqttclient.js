import mqtt from "mqtt";
import { logger } from "../server.js";
import { recordRuntimeEvent, setMqttStatus } from "./runtime.js";
const protocol = process.env.MQTT_PROTOCOL || "mqtt";
const host = process.env.MQTT_HOST || "localhost";
const port = process.env.MQTT_PORT || "1883";
const clientId = `mqtt_${Math.random().toString(16).slice(3)}`;
const connectUrl = `${protocol}://${host}:${port}`;
function createTestClient() {
    const fakeClient = {
        connected: false,
        publish(_topic, _payload, callback) {
            callback?.(null);
            return true;
        },
        on() {
            return fakeClient;
        },
    };
    return fakeClient;
}
const shouldDisableMqtt = process.env.NODE_ENV === "test" || process.env.PIPHI_DISABLE_MQTT === "true";
export const client = shouldDisableMqtt
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
client.on("error", (error) => {
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
