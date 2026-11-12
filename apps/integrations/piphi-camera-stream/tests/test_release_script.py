from __future__ import annotations

import runpy
from pathlib import Path


ROOT = Path(__file__).parents[1]


def test_release_script_updates_runtime_version_constant() -> None:
    release_module = runpy.run_path(str(ROOT / "scripts" / "release.py"))

    rendered = release_module["render_runtime_version"](
        'INTEGRATION_VERSION = "0.1.1"\n', "0.1.2"
    )

    assert rendered == 'INTEGRATION_VERSION = "0.1.2"\n'


def test_release_workflow_commits_runtime_version_file() -> None:
    workflow = (ROOT / ".github" / "workflows" / "release.yml").read_text()

    assert "git add src/piphi_camera_stream/settings.py" in workflow
