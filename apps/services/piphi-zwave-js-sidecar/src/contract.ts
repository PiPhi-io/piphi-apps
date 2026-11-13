export const endpoints = {
  health: "/health",
  diagnostics: "/diagnostics",
  discover: "/discover",
  entities: "/entities",
  state: "/state",
  config: "/config",
  configSync: "/config/sync",
  deconfigure: "/deconfigure",
  uiConfig: "/ui-config",
  events: "/events",
  zwaveEvents: "/v1/zwave/events",
  command: "/command",
} as const;

export const requiredEndpoints = ["health", "entities", "command", "config", "ui_config"] as const;

export const capabilities = {
  "connected": {
    "kind": "sensor",
    "unit": "bool"
  },
  "driver_ready": { "kind": "sensor", "unit": "bool" },
  "controller_ready": { "kind": "sensor", "unit": "bool" },
  "node_count": { "kind": "sensor", "unit": "nodes" },
  "ready_node_count": { "kind": "sensor", "unit": "nodes" },
  "sleeping_node_count": { "kind": "sensor", "unit": "nodes" },
  "dead_node_count": { "kind": "sensor", "unit": "nodes" },
  "event_queue_depth": { "kind": "sensor", "unit": "events" },
  "dropped_event_count": { "kind": "sensor", "unit": "events" },
  "command_queue_depth": { "kind": "sensor", "unit": "commands" },
  "refresh_controller_information": {
    "kind": "action"
  },
  "reconnect_driver": {
    "kind": "action"
  },
  "ping_node": {
    "kind": "action"
  },
  "request_node_interview": {
    "kind": "action"
  },
  "refresh_node_values": {
    "kind": "action"
  }
} as const;

export const commands = {
  "refresh_controller_information": {
    "description": "Read the current controller and queue state.",
    "timeout_ms": 10000
  },
  "reconnect_driver": {
    "description": "Restart the managed Z-Wave JS driver.",
    "timeout_ms": 30000
  },
  "ping_node": {
    "description": "Ask Z-Wave JS to test whether a node is reachable.",
    "timeout_ms": 30000
  },
  "request_node_interview": {
    "description": "Request a new Z-Wave JS interview for one node.",
    "timeout_ms": 120000
  },
  "refresh_node_values": {
    "description": "Refresh the known values for one node.",
    "timeout_ms": 120000
  }
} as const;

export const configSchema = {
  "schema": {
    "title": "Piphi Zwave Js Sidecar Setup",
    "type": "object",
    "required": [
      "controller_path"
    ],
    "properties": {
      "controller_path": {
        "type": "string",
        "title": "Controller device path",
        "pattern": "^/dev/serial/(by-id|by-path)/.+$"
      },
      "alias": {
        "type": "string",
        "title": "Alias"
      },
      "event_queue_capacity": {
        "type": "integer",
        "title": "Event replay capacity",
        "minimum": 10,
        "maximum": 10000,
        "default": 1000
      }
    }
  },
  "uiSchema": {
    "controller_path": {
      "placeholder": "/dev/serial/by-id/usb-Z-Wave_Controller-if00"
    },
    "alias": {
      "placeholder": "Office Device"
    },
    "event_queue_capacity": { "ui:widget": "number" }
  }
} as const;

export const fallbackEntity = {
  "id": "zwave-js-service",
  "name": "Z-Wave JS Service",
  "device_id": "zwave-js-service",
  "entity_type": "service",
  "capabilities": [
    "connected",
    "driver_ready",
    "controller_ready",
    "node_count",
    "ready_node_count",
    "sleeping_node_count",
    "dead_node_count",
    "event_queue_depth",
    "dropped_event_count",
    "command_queue_depth",
    "refresh_controller_information",
    "reconnect_driver",
    "ping_node",
    "request_node_interview",
    "refresh_node_values"
  ],
  "available_commands": [
    {
      "id": "refresh_controller_information",
      "label": "Refresh controller",
      "kind": "action"
    },
    { "id": "reconnect_driver", "label": "Reconnect driver", "kind": "action" },
    { "id": "ping_node", "label": "Ping node", "kind": "action" },
    { "id": "request_node_interview", "label": "Interview node", "kind": "action" },
    { "id": "refresh_node_values", "label": "Refresh node values", "kind": "action" }
  ],
  "dashboard": {
    "allowed_widgets": [
      "tile",
      "stat",
      "button"
    ],
    "default_widget": "tile"
  }
} as const;
