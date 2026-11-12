# Widget-only registry contract proposal

PiPhi's existing registry stores runtime integrations. A custom dashboard package
needs a separate install lifecycle because it has no container, configuration
endpoint, entities, or commands of its own.

The proposed `type: "widget"` entry reuses common catalog and Marketplace v2
fields and adds `manifest_path`, an immutable release asset plus integrity, and
browser or trusted-host runtime requirements.

Core should download the immutable release asset, verify its digest, validate the
Widget SDK manifest, verify each declared asset's SRI, and extract it beneath a
widget-specific cache directory. It should serve those assets from an untrusted
media origin and merge installed packages into the dashboard widget catalog.

Uninstall must refuse or explicitly confirm removal while dashboards reference
the package. Updating a widget changes executable catalog metadata but must not
rewrite saved dashboard bindings or settings.

For this reference widget, Core owns signaling. `host.openCameraSession` derives
the configured camera solely from the saved binding, validates the `camera`
permission and `camera_stream` capability, forwards a bounded SDP offer to the
registered camera gateway, and returns a bounded SDP answer plus an opaque
session ID. Secrets, upstream URLs, ICE credentials, and integration diagnostics
are not exposed to iframe code.
