from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from piphi_network_tp_link.lib.qualification import (
    load_local_env,
    qualify_read_only,
    sanitize_qualification_snapshot,
)


def _snapshot(*, mac: str = "00:11:22:33:44:55") -> dict:
    return {
        "host": "192.168.1.20",
        "alias": "Private room name",
        "mac": mac,
        "model": "SYNTHETIC-MONITOR",
        "device_type": "plug",
        "sys_info": {"sw_ver": "1.2.3", "deviceId": "private-id", "latitude": 1},
        "capabilities": ["refresh", "switch"],
        "features": {
            "state": {
                "id": "state",
                "type": "binary_sensor",
                "value": True,
                "writable": True,
            }
        },
        "energy": {"current_power_w": 12.5},
        "supported_commands": [
            {"id": "refresh"},
            {"id": "read_energy"},
        ],
        "children": [],
    }


def test_qualification_snapshot_excludes_identity_alias_host_and_values() -> None:
    sanitized = sanitize_qualification_snapshot(_snapshot())
    encoded = repr(sanitized)
    assert "192.168.1.20" not in encoded
    assert "00:11:22:33:44:55" not in encoded
    assert "Private room name" not in encoded
    assert "private-id" not in encoded
    assert "12.5" not in encoded
    assert "'value'" not in encoded
    assert sanitized["versions"] == {"sw_ver": "1.2.3"}


def test_qualification_rejects_advertised_write_commands() -> None:
    snapshot = _snapshot()
    snapshot["supported_commands"].append({"id": "turn_on"})
    with pytest.raises(ValueError, match="unqualified write"):
        sanitize_qualification_snapshot(snapshot)


def test_qualification_rejects_child_write_commands() -> None:
    snapshot = _snapshot()
    snapshot["children"] = [
        {
            "model": "SYNTHETIC-CHILD",
            "capabilities": ["switch"],
            "supported_commands": [{"id": "turn_on"}],
        }
    ]
    with pytest.raises(ValueError, match="child snapshot.*unqualified write"):
        sanitize_qualification_snapshot(snapshot)


def test_local_env_loader_decodes_wizard_quoting(tmp_path: Path) -> None:
    env_path = tmp_path / ".qualification.env"
    env_path.write_text(
        "PIPHI_TP_LINK_RUN_HARDWARE='1'\n"
        "PIPHI_TP_LINK_QUALIFICATION_PASSWORD='space and '\\''quote'\n",
        encoding="utf-8",
    )

    assert load_local_env(env_path) == {
        "PIPHI_TP_LINK_RUN_HARDWARE": "1",
        "PIPHI_TP_LINK_QUALIFICATION_PASSWORD": "space and 'quote",
    }


def test_read_only_qualification_requires_stable_identity_and_capabilities() -> None:
    states = iter([_snapshot(), _snapshot(mac="00:11:22:33:44:66")])

    async def fake_fetcher(**kwargs):
        return next(states)

    with pytest.raises(ValueError, match="identity changed"):
        asyncio.run(
            qualify_read_only(
                host="192.168.1.20",
                username=None,
                password=None,
                samples=2,
                fetcher=fake_fetcher,
            )
        )


def test_read_only_qualification_requires_stable_profile() -> None:
    first = _snapshot()
    second = _snapshot()
    second["features"]["state"]["writable"] = False
    states = iter([first, second])

    async def fake_fetcher(**kwargs):
        return next(states)

    with pytest.raises(ValueError, match="qualification profile changed"):
        asyncio.run(
            qualify_read_only(
                host="192.168.1.20",
                username=None,
                password=None,
                samples=2,
                fetcher=fake_fetcher,
            )
        )
