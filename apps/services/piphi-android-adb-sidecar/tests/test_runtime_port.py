import pytest

from piphi_android_adb_sidecar.settings import DEFAULT_PORT, runtime_port


def test_runtime_port_uses_core_assignment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PORT", "43127")
    assert runtime_port() == 43127


def test_runtime_port_rejects_invalid_assignment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PORT", "invalid")
    with pytest.raises(ValueError, match="PORT"):
        runtime_port()


def test_runtime_port_uses_default_when_unmanaged(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("PORT", raising=False)
    assert runtime_port() == DEFAULT_PORT
