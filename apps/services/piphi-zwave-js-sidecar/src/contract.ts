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
  command: "/command",
} as const;

export const requiredEndpoints = ["health", "entities", "command", "config", "ui_config"] as const;

export const capabilities = {
  "connected": {
    "kind": "sensor",
    "unit": "bool"
  },
  "refresh": {
    "kind": "action"
  }
} as const;

export const commands = {
  "refresh": {
    "description": "Refresh the device state.",
    "timeout_ms": 5000
  }
} as const;

export const configSchema = {
  "schema": {
    "title": "Piphi Zwave Js Sidecar Setup",
    "type": "object",
    "required": [
      "host"
    ],
    "properties": {
      "host": {
        "type": "string",
        "title": "Host"
      },
      "alias": {
        "type": "string",
        "title": "Alias"
      },
      "service_name": {
        "type": "string",
        "title": "Service Name"
      }
    }
  },
  "uiSchema": {
    "host": {
      "placeholder": "192.168.1.50"
    },
    "alias": {
      "placeholder": "Office Device"
    },
    "service_name": {
      "placeholder": "local-helper"
    }
  }
} as const;

export const fallbackEntity = {
  "id": "zwave-js-service",
  "name": "Z-Wave JS Service",
  "device_id": "zwave-js-service",
  "entity_type": "service",
  "capabilities": [
    "connected",
    "refresh"
  ],
  "available_commands": [
    {
      "id": "refresh",
      "label": "Refresh",
      "kind": "action"
    }
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
