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
    assert force_include["src/manifest.json"] == "piphi_network_i2c/manifest.json"
    assert force_include["src/behaviors.json"] == "piphi_network_i2c/behaviors.json"
    assert version == app["packages"][0]["version"] == manifest["version"]
    assert manifest["image"] == f"ghcr.io/piphi-io/i2c-integration:{version}"
    container = manifest["runtime"]["linux"]["container"]
    assert container["privileged"] is False
    assert container["read_only"] is True
    assert not container.get("devices")
    assert "group_add" not in container
    assert container["ports"] == [{"container": 3674, "protocol": "tcp"}]
    assert manifest["runtime_contract"] == {
        "version": 1,
        "port_binding": "core_allocated",
        "port_env": "PIPHI_I2C_PORT",
    }
    assert container["cap_drop"] == ["ALL"]
    assert "no-new-privileges:true" in container["security_opt"]
    source = "\n".join(path.read_text() for path in (ROOT / "src").rglob("*.py"))
    assert "I2C_SLAVE_FORCE" not in source
    assert "/unbind" not in source and "/bind" not in source
    dockerfile = (ROOT / "Dockerfile").read_text()
    assert "@sha256:" in dockerfile and "USER piphi" in dockerfile
    readme = (ROOT / "README.md").read_text()
    assert "-p 127.0.0.1:3674:3674" in readme
    assert "standalone ingress-auth boundary" in readme
    assert "dynamic supplementary device GID" in readme
    adapter_options = manifest["runtime"]["linux"]["discovery"]["inputs"][0]["options"]
    assert adapter_options == ["mock"]
    options = manifest["runtime"]["linux"]["discovery"]["inputs"][4]["options"]
    assert options == ["auto", "bme680", "bme280", "bmp280", "generic"]
    assert (ROOT / "CHANGELOG.md").exists()


if __name__ == "__main__":
    main()
