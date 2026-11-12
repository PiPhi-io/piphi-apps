from __future__ import annotations

from starlette.routing import Mount

from piphi_network_nord_pool.app import create_app


def test_runtime_mounts_configured_widget_directory(tmp_path, monkeypatch) -> None:
    asset = tmp_path / "nord-pool-price" / "dist" / "widget.js"
    asset.parent.mkdir(parents=True)
    asset.write_text("export const ready = true;", encoding="utf-8")
    monkeypatch.setenv("PIPHI_WIDGET_DIR", str(tmp_path))

    mount = next(
        route for route in create_app().routes
        if isinstance(route, Mount) and route.path == "/widgets"
    )
    assert mount.app.directory == tmp_path
