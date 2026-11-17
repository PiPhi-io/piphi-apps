from __future__ import annotations

import json
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    project = tomllib.loads((ROOT / "pyproject.toml").read_text())
    app = json.loads((ROOT / "piphi-app.json").read_text())
    manifest = json.loads((ROOT / "src/manifest.json").read_text())
    version = project["project"]["version"]
    force_include = project["tool"]["hatch"]["build"]["targets"]["wheel"]["force-include"]
    assert force_include["src/manifest.json"] == "piphi_network_spi/manifest.json"
    assert force_include["src/behaviors.json"] == "piphi_network_spi/behaviors.json"
    assert version == app["packages"][0]["version"] == manifest["version"]
    assert manifest["image"] == f"ghcr.io/piphi-io/spi-integration:{version}"
    container = manifest["runtime"]["linux"]["container"]
    assert container["privileged"] is False
    assert container["read_only"] is True
    assert not container.get("devices")
    assert container["ports"] == [{"container": 3675}]
    assert manifest["runtime_contract"] == {
        "version": 1,
        "port_binding": "core_allocated",
        "port_env": "PIPHI_SPI_PORT",
    }
    assert container["cap_drop"] == ["ALL"]
    assert "no-new-privileges:true" in container["security_opt"]
    assert manifest["runtime"]["linux"]["discovery"]["inputs"][0]["options"] == ["mock"]
    source = "\n".join(path.read_text() for path in (ROOT / "src").rglob("*.py"))
    assert "SPI_IOC" not in source
    assert "/unbind" not in source and "/bind" not in source
    dockerfile = (ROOT / "Dockerfile").read_text()
    assert "@sha256:" in dockerfile and "USER piphi" in dockerfile
    assert "standalone ingress-auth boundary" in (ROOT / "README.md").read_text()
    assert "-p 127.0.0.1:3675:3675" in (ROOT / "README.md").read_text()
    assert (ROOT / "CHANGELOG.md").exists()


if __name__ == "__main__":
    main()
