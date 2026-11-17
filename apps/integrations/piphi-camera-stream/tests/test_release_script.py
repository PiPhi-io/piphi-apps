from __future__ import annotations

import json
import runpy
from pathlib import Path

ROOT = Path(__file__).parents[1]


def test_release_script_updates_runtime_version_constant() -> None:
    release_module = runpy.run_path(str(ROOT / "scripts" / "release.py"))

    rendered = release_module["render_runtime_version"](
        'INTEGRATION_VERSION = "0.1.1"\n', "0.1.2"
    )

    assert rendered == 'INTEGRATION_VERSION = "0.1.2"\n'


def test_package_declares_required_central_ci_and_container_release() -> None:
    package = json.loads((ROOT / "piphi-app.json").read_text())

    assert package["ci"]["enforcement"] == "full"
    assert "pdm run pytest" in package["ci"]["commands"]
    assert "pdm run python scripts/validate.py" in package["ci"]["commands"]
    assert package["ci"]["build_container"] is True
    assert package["packages"][0]["release"]["tag"] == "apps/{package_id}/v{version}"
