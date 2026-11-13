import assert from "node:assert/strict";
import test from "node:test";

import {
  applyConfig,
  executeDriverCommand,
  registry,
  removeConfig,
  setDriverSessionFactory,
} from "../src/state.js";
import type {
  DriverSession,
  DriverSessionFactory,
  DriverSnapshot,
} from "../src/types.js";

function transactionalFactory(): DriverSessionFactory {
  return ({ config }) => {
    let lifecycle: DriverSnapshot["lifecycle"] = "stopped";
    const shouldFail = config.alias === "broken replacement";
    const session: DriverSession = {
      async start() {
        if (shouldFail) throw new Error("replacement_start_failed");
        lifecycle = "ready";
      },
      async stop() {
        lifecycle = "stopped";
      },
      async execute(command) {
        return { accepted: true, command: command.name };
      },
      snapshot() {
        return {
          lifecycle,
          driverReady: lifecycle === "ready",
          controllerReady: lifecycle === "ready",
          controllerPathSuffix: "controller",
          nodeCount: 0,
          readyNodeCount: 0,
          sleepingNodeCount: 0,
          deadNodeCount: 0,
          reconnectCount: 0,
        };
      },
      nodesSnapshot() {
        return [];
      },
    };
    return session;
  };
}

test("failed reconfiguration restores the previous driver and registry entry", async () => {
  setDriverSessionFactory(transactionalFactory());
  const configId = "transactional-controller";
  try {
    await applyConfig({
      id: configId,
      controller_path: "/dev/serial/by-id/working-controller",
      alias: "working controller",
    });

    await assert.rejects(
      applyConfig({
        id: configId,
        controller_path: "/dev/serial/by-id/replacement-controller",
        alias: "broken replacement",
      }),
      /replacement_start_failed/,
    );

    assert.equal(registry.get(configId)?.alias, "working controller");
    const result = await executeDriverCommand(configId, "refresh_controller_information", {});
    assert.equal(result.accepted, true);
  } finally {
    await removeConfig(configId);
  }
});

test("failed initial configuration leaves no active registry entry", async () => {
  setDriverSessionFactory(transactionalFactory());
  const configId = "failed-initial-controller";
  await assert.rejects(
    applyConfig({
      id: configId,
      controller_path: "/dev/serial/by-id/failed-controller",
      alias: "broken replacement",
    }),
    /replacement_start_failed/,
  );
  assert.equal(registry.get(configId), undefined);
});
