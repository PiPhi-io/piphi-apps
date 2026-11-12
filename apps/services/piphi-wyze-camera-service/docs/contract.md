# Camera bridge service contract

`camera.bridge.wyze.v1` is an internal service-to-service contract.

The future Wyze Camera integration owns homeowner authorization and sends secret configuration
to `PUT /v1/wyze-bridge/config`. The bridge starts the pinned upstream runtime with authenticated
streams and returns descriptors from `GET /v1/wyze-bridge/cameras`. Camera Media Service consumes
the returned RTSP source through Core; browser widgets never receive the source URL.

The service may be healthy while awaiting configuration. After configuration, an exited bridge
process changes health to degraded. Removing configuration terminates the child process and drops
all adapter-held credentials and generated stream passwords.

No automation actions, first-class devices, telemetry, or dashboard widgets are provided by this
service.
