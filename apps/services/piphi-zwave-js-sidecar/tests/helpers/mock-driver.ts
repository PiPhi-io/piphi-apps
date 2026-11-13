import type {
  DriverCommand,
  DriverSession,
  DriverSessionFactory,
  DriverSnapshot,
} from "../../src/types.js";

export function createMockDriverFactory(): DriverSessionFactory {
  return ({ config, onEvent }) => {
    let lifecycle: DriverSnapshot["lifecycle"] = "stopped";
    const session: DriverSession = {
      async start() {
        lifecycle = "ready";
        onEvent({
          schema_version: "piphi.zwave.event.v1",
          occurred_at: "2026-11-13T12:00:00.000Z",
          event_type: "driver.ready",
          source: "zwave-js",
          payload: { node_count: 5 },
        });
      },
      async stop() {
        lifecycle = "stopped";
      },
      async execute(command: DriverCommand) {
        return "nodeId" in command
          ? { accepted: true, node_id: command.nodeId }
          : { accepted: true };
      },
      snapshot() {
        return {
          lifecycle,
          driverReady: lifecycle === "ready",
          controllerReady: lifecycle === "ready",
          controllerPathSuffix: config.controller_path.split("/").at(-1) ?? "mock",
          driverVersion: "15.32.3-test",
          nodeCount: 5,
          readyNodeCount: 4,
          sleepingNodeCount: 1,
          deadNodeCount: 0,
          reconnectCount: 0,
        };
      },
    };
    return session;
  };
}
