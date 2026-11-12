# Core manifest contract: configuration instance limits

## Manifest field

```json
{
  "config": {
    "maximum_instances": 1
  }
}
```

`config.maximum_instances` is an optional positive integer. It limits active and inactive persisted `IntegrationConfig` records for one installed `Integration` across the Core, not the number of entities discovered behind that configuration and not the number of dashboard widget instances.

For Sense, one configuration represents one authenticated Sense account/session. That configuration may expose one monitor entity and many detected-device entities.

## Core behavior

Core validates the field as an integer `>= 1`. In `ConfigRouter.validate_device_container`, after resolving the integration and before contacting the runtime, it serializes creation for that integration and counts existing `IntegrationConfig` rows for the `integration_id`. When the count is at the declared limit, Core returns HTTP `409` with a stable payload:

```json
{
  "error": "integration_instance_limit_reached",
  "message": "Sense Energy allows at most 1 configured instance.",
  "maximum_instances": 1,
  "integration_id": "..."
}
```

Updates to an existing configuration do not consume another slot. Deleting a configuration frees its slot. The per-integration creation lock remains held through persistence so two concurrent requests in the Core process cannot both pass the count check.

## Core test matrix

1. Manifest normalization preserves `config.maximum_instances: 1`.
2. Manifest validation rejects zero, negative, boolean, float, and string values.
3. First configuration succeeds.
4. Second distinct configuration returns `409` before runtime `/config` is called.
5. Updating the existing configuration succeeds at the limit.
6. Removing the existing configuration allows a replacement.
7. A manifest without the field remains unlimited for backward compatibility.
8. Two concurrent creates cannot exceed the limit.

The Sense runtime also enforces the limit as defense in depth, which protects installations running a Core version that predates this contract field.
