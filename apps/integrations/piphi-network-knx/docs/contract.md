# Runtime contract

- Integration: `piphi-network-knx`
- Version: `0.2.0`
- Kind/preset/domain: `integration` / `protocol-bridge` / `bridge`
- Port: `4223`

`GET /health` is public. Every other endpoint requires `X-PiPhi-Integration-Token` matching `PIPHI_INTEGRATION_INTERNAL_TOKEN`; the runtime fails closed when no token is configured.

Required endpoints are `/health`, `/entities`, `/command`, `/config`, and `/ui-config`. Discovery, snapshot sync, removal, state, diagnostics, contract metadata, and events are also exposed.

## Commands

`read_datapoint` accepts `params.datapoint_id`. The ID is resolved only inside the selected configuration and cannot be a group address.

`write_datapoint` accepts `params.datapoint_id` and `params.value`. Dispatch succeeds only if global writes and that exact datapoint are enabled. The entity/DPT matrix validates the value before xknx receives it. Accepted transmission remains feedback-pending; timeout returns an unknown outcome and is not retried.

```json
{
  "contract_version": "automation.runtime.command.v1",
  "command": "write_datapoint",
  "target": {"config_id": "main-building"},
  "params": {"datapoint_id": "office_light", "value": true},
  "capability": "write_datapoint",
  "capability_requirements": ["write_datapoint"]
}
```

Keep `manifest.json`, `capability-catalog.json`, `src/behaviors.json`, and executable contract tests synchronized.
