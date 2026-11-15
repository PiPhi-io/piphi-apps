from __future__ import annotations

import platform
from pathlib import Path
from typing import Any, Protocol


class BlueZTransport(Protocol):
    async def diagnostics(self, adapter: str) -> dict[str, Any]: ...
    async def recover(self, adapter: str) -> bool: ...


class DbusFastBlueZTransport:
    """Narrow BlueZ Adapter1 access; never exposes the D-Bus object tree."""

    async def _adapters(self) -> tuple[Any, dict[str, dict[str, Any]]]:
        from dbus_fast import BusType, Message, MessageType
        from dbus_fast.aio import MessageBus

        bus = await MessageBus(bus_type=BusType.SYSTEM).connect()
        reply = await bus.call(Message(
            destination="org.bluez",
            path="/",
            interface="org.freedesktop.DBus.ObjectManager",
            member="GetManagedObjects",
        ))
        if reply.message_type == MessageType.ERROR:
            bus.disconnect()
            raise RuntimeError("BlueZ object manager is unavailable")
        objects = reply.body[0] if reply.body else {}
        adapters = {
            str(path): interfaces["org.bluez.Adapter1"]
            for path, interfaces in objects.items()
            if isinstance(interfaces, dict) and "org.bluez.Adapter1" in interfaces
        }
        return bus, adapters

    @staticmethod
    def _select(adapters: dict[str, dict[str, Any]], adapter: str) -> tuple[str, dict[str, Any]] | None:
        if not adapters:
            return None
        if adapter != "default":
            suffix = f"/{adapter}"
            for path, properties in adapters.items():
                if path.endswith(suffix):
                    return path, properties
            return None
        return sorted(adapters.items())[0]

    async def diagnostics(self, adapter: str) -> dict[str, Any]:
        bus, adapters = await self._adapters()
        try:
            selected = self._select(adapters, adapter)
            if selected is None:
                return {"available": False, "adapter_count": len(adapters)}
            _path, properties = selected
            powered = properties.get("Powered")
            discovering = properties.get("Discovering")
            return {
                "available": True,
                "adapter_count": len(adapters),
                "adapter_powered": bool(getattr(powered, "value", powered)),
                "adapter_discovering": bool(getattr(discovering, "value", discovering)),
            }
        finally:
            bus.disconnect()

    async def recover(self, adapter: str) -> bool:
        from dbus_fast import Message, MessageType, Variant

        bus, adapters = await self._adapters()
        try:
            selected = self._select(adapters, adapter)
            if selected is None:
                return False
            path, properties = selected
            powered = properties.get("Powered")
            if bool(getattr(powered, "value", powered)):
                return True
            reply = await bus.call(Message(
                destination="org.bluez",
                path=path,
                interface="org.freedesktop.DBus.Properties",
                member="Set",
                signature="ssv",
                body=["org.bluez.Adapter1", "Powered", Variant("b", True)],
            ))
            return reply.message_type != MessageType.ERROR
        finally:
            bus.disconnect()


class BlueZCapabilityAdapter:
    def __init__(self, adapter: str = "default", transport: BlueZTransport | None = None) -> None:
        self.adapter = adapter
        self.transport = transport or DbusFastBlueZTransport()

    async def diagnostics(self) -> dict[str, Any]:
        try:
            result = await self.transport.diagnostics(self.adapter)
        except Exception as exc:
            return {
                "supported": True,
                "available": False,
                "error": type(exc).__name__,
                **self._rfkill(),
            }
        return {"supported": True, **result, **self._rfkill()}

    async def recover(self) -> bool:
        try:
            return await self.transport.recover(self.adapter)
        except Exception:
            return False

    @staticmethod
    def _rfkill() -> dict[str, bool | None]:
        soft: bool | None = None
        hard: bool | None = None
        for entry in Path("/sys/class/rfkill").glob("rfkill*"):
            try:
                if (entry / "type").read_text().strip() != "bluetooth":
                    continue
                soft_value = (entry / "soft").read_text().strip() == "1"
                hard_value = (entry / "hard").read_text().strip() == "1"
                soft = soft_value if soft is None else soft or soft_value
                hard = hard_value if hard is None else hard or hard_value
            except OSError:
                continue
        return {"rfkill_soft_blocked": soft, "rfkill_hard_blocked": hard}


def default_capability_adapter(adapter: str = "default"):
    if platform.system().lower() == "linux":
        return BlueZCapabilityAdapter(adapter)
    from .scanner import NoopCapabilityAdapter

    return NoopCapabilityAdapter()
