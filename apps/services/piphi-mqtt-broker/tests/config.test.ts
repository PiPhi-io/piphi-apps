import test from "node:test";
import assert from "node:assert/strict";

import { loadBrokerConfig } from "../src/config.js";
import { renderMosquittoConfig } from "../src/mosquitto.js";

test("loadBrokerConfig applies defaults", () => {
  const config = loadBrokerConfig({ MQTT_ALLOW_ANONYMOUS: "true" });

  assert.equal(config.port, 1883);
  assert.equal(config.allowAnonymous, true);
  assert.equal(config.topicPrefix, "piphi");
});

test("loadBrokerConfig gives the Core-assigned PORT precedence", () => {
  const config = loadBrokerConfig({ PORT: "43127", MQTT_PORT: "1884", MQTT_ALLOW_ANONYMOUS: "true" });
  assert.equal(config.port, 43127);
  assert.throws(() => loadBrokerConfig({ PORT: "invalid", MQTT_ALLOW_ANONYMOUS: "true" }), /managed runtime PORT/);
});

test("renderMosquittoConfig includes password file when credentials exist", () => {
  const config = loadBrokerConfig({
    MQTT_ALLOW_ANONYMOUS: "false",
    MQTT_USERNAME: "piphi",
    MQTT_PASSWORD: "secret",
  });

  const rendered = renderMosquittoConfig(config);

  assert.match(rendered, /listener 1883 0.0.0.0/);
  assert.match(rendered, /password_file \/mosquitto\/config\/passwordfile/);
});

test("loadBrokerConfig requires credentials when anonymous is disabled", () => {
  assert.throws(
    () => loadBrokerConfig({ MQTT_ALLOW_ANONYMOUS: "false" }),
    /MQTT credentials are required/,
  );
});
