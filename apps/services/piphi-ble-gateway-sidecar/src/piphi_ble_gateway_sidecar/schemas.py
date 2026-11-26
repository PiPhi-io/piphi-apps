from __future__ import annotations

from piphi_runtime_kit_python import RuntimeConfig


class DeviceConfig(RuntimeConfig):
    alias: str | None = None
    service_name: str | None = None
