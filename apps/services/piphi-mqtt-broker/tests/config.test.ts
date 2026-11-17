import test from "node:test";
import assert from "node:assert/strict";

import { loadBrokerConfig } from "../src/config.js";
import { renderIdentityAcl } from "../src/identity.js";
import { renderMosquittoConfig } from "../src/mosquitto.js";

const authenticated = {
  MQTT_ALLOW_PLAINTEXT: "true",
  MQTT_USERNAME: "piphi",
  MQTT_PASSWORD: "secret",
};

test("loadBrokerConfig applies bounded defaults", () => {
  const config = loadBrokerConfig(authenticated);
  assert.equal(config.port, 1883);
  assert.equal(config.allowAnonymous, false);
  assert.equal(config.topicPrefix, "piphi");
  assert.equal(config.maxConnections, 256);
  assert.equal(config.maxQueuedBytes, 16_777_216);
  assert.equal(config.memoryLimit, 268_435_456);
  assert.equal(config.maxKeepalive, 300);
});

test("loadBrokerConfig gives the Core-assigned PORT precedence", () => {
  const config = loadBrokerConfig({ ...authenticated, PORT: "43127", MQTT_PORT: "1884" });
  assert.equal(config.port, 43127);
  assert.throws(() => loadBrokerConfig({ ...authenticated, PORT: "invalid" }), /managed runtime PORT/);
});

test("renderMosquittoConfig enables ACLs and resource limits", () => {
  const config = loadBrokerConfig(authenticated);
  const rendered = renderMosquittoConfig(config);
  assert.match(rendered, /listener 1883 0.0.0.0/);
  assert.match(rendered, /password_file \/mosquitto\/config\/identity\/current\/passwordfile/);
  assert.match(rendered, /acl_file \/mosquitto\/config\/identity\/current\/aclfile/);
  assert.match(rendered, /max_packet_size 1048576/);
  assert.match(rendered, /memory_limit 268435456/);
  assert.match(rendered, /connection_messages false/);
  assert.equal(renderIdentityAcl({
    schemaVersion: 1,
    sourceDigest: "test",
    principals: [{ username: "piphi", passwordSecretFile: "environment:MQTT_PASSWORD", read: ["piphi/#"], write: ["piphi/#"], health: true, namespace: "legacy" }],
  }), "user piphi\ntopic deny readwrite $SYS/#\ntopic deny readwrite $CONTROL/#\ntopic read piphi/#\ntopic write piphi/#\n");
});

test("loadBrokerConfig fails closed without authentication or a transport policy", () => {
  assert.throws(() => loadBrokerConfig({ MQTT_ALLOW_PLAINTEXT: "true" }), /credentials or MQTT_AUTH_POLICY_FILE are required/);
  assert.throws(() => loadBrokerConfig({ MQTT_USERNAME: "piphi", MQTT_PASSWORD: "secret" }), /Plaintext MQTT must be explicitly enabled/);
  assert.throws(() => loadBrokerConfig({ MQTT_ALLOW_ANONYMOUS: "true", MQTT_ALLOW_PLAINTEXT: "true" }), /Anonymous MQTT is not supported/);
});

test("loadBrokerConfig rejects directive injection and unsafe paths", () => {
  assert.throws(() => loadBrokerConfig({ ...authenticated, MQTT_HOST: "0.0.0.0\nallow_anonymous true" }), /Invalid MQTT_HOST/);
  assert.throws(() => loadBrokerConfig({ ...authenticated, MQTT_TOPIC_PREFIX: "piphi/#" }), /Invalid MQTT_TOPIC_PREFIX/);
  assert.throws(() => loadBrokerConfig({ ...authenticated, MQTT_CONFIG_OUTPUT: "/tmp/mosquitto.conf" }), /Invalid MQTT_CONFIG_OUTPUT/);
  assert.throws(() => loadBrokerConfig({ ...authenticated, MQTT_PASSWORD_SECRET_FILE: "/run/secrets-escape/password", MQTT_PASSWORD: undefined }), /Invalid MQTT_PASSWORD_SECRET_FILE/);
  assert.throws(() => loadBrokerConfig({ ...authenticated, MQTT_MEMORY_LIMIT: "4294967296" }), /exceeds/);
});

test("TLS requires a certificate and key and renders verified TLS", () => {
  assert.throws(() => loadBrokerConfig({ MQTT_USERNAME: "piphi", MQTT_PASSWORD: "secret", MQTT_TLS_ENABLED: "true" }), /TLS_CERT_FILE/);
  const config = loadBrokerConfig({
    MQTT_USERNAME: "piphi",
    MQTT_PASSWORD_SECRET_FILE: "/run/secrets/mqtt-password",
    MQTT_TLS_ENABLED: "true",
    MQTT_TLS_CERT_FILE: "/run/secrets/server.crt",
    MQTT_TLS_KEY_FILE: "/run/secrets/server.key",
    MQTT_TLS_CA_FILE: "/run/secrets/ca.crt",
  });
  const rendered = renderMosquittoConfig(config);
  assert.match(rendered, /certfile \/run\/secrets\/server.crt/);
  assert.match(rendered, /tls_version tlsv1.2/);
  assert.doesNotMatch(rendered, /allow_anonymous true/);
  assert.throws(() => loadBrokerConfig({
    MQTT_USERNAME: "piphi",
    MQTT_PASSWORD_SECRET_FILE: "/run/secrets/mqtt-password",
    MQTT_TLS_ENABLED: "true",
    MQTT_TLS_CERT_FILE: "/run/secrets/server.crt",
    MQTT_TLS_KEY_FILE: "/run/secrets/server.key",
    MQTT_TLS_CA_FILE: "/run/secrets/ca.crt",
    MQTT_TLS_REQUIRE_CLIENT_CERTIFICATE: "true",
  }), /MQTT_HEALTH_TLS_CERT_FILE/);
});

test("auth policy mode replaces legacy credentials", () => {
  const config = loadBrokerConfig({ MQTT_ALLOW_PLAINTEXT: "true", MQTT_AUTH_POLICY_FILE: "/run/secrets/mqtt-policy.json" });
  assert.equal(config.authPolicyFile, "/run/secrets/mqtt-policy.json");
  assert.match(renderMosquittoConfig(config), /acl_file/);
  assert.throws(() => loadBrokerConfig({ ...authenticated, MQTT_AUTH_POLICY_FILE: "/run/secrets/mqtt-policy.json" }), /cannot be combined/);
});
