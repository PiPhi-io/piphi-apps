from __future__ import annotations

import uvicorn

from piphi_webrtc_sidecar import main


def test_runtime_disables_access_logs(monkeypatch) -> None:
    calls: list[tuple[object, dict[str, object]]] = []

    def fake_run(app: object, **kwargs: object) -> None:
        calls.append((app, kwargs))

    monkeypatch.setattr(uvicorn, "run", fake_run)
    monkeypatch.setattr(main, "runtime_port", lambda: 4321)

    main.main()

    assert calls == [
        (
            main.app,
            {"host": "0.0.0.0", "port": 4321, "access_log": False},
        )
    ]
