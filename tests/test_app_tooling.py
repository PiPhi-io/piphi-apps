from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import app_tooling


class AppToolingTests(unittest.TestCase):
    def app_fixture(self, root: Path, *, language: str = "python") -> Path:
        path = root / "apps" / "integrations" / "example"
        path.mkdir(parents=True)
        (path / "manifest.json").write_text(
            json.dumps(
                {
                    "id": "example",
                    "version": "1.2.3",
                    "image": "ghcr.io/piphi-io/example:1.2.3",
                }
            ),
            encoding="utf-8",
        )
        (path / "Dockerfile").write_text("FROM scratch\n", encoding="utf-8")
        (path / "piphi-app.json").write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "slug": "example",
                    "source": {"imported_from": None},
                    "languages": [language],
                    "toolchains": {language: "stable"},
                    "ci": {
                        "enforcement": "full",
                        "commands": ["true"],
                        "build_container": True,
                    },
                    "packages": [
                        {
                            "id": "example",
                            "type": "integration",
                            "version": "1.2.3",
                            "manifest": "manifest.json",
                            "artifact": {
                                "kind": "oci",
                                "context": ".",
                                "dockerfile": "Dockerfile",
                            },
                            "publishing": {
                                "mode": "piphi_managed",
                                "environment": "release",
                                "primary": {
                                    "registry": "ghcr.io",
                                    "repository": "piphi-io/example",
                                },
                                "mirrors": [],
                            },
                            "release": {
                                "tag": "apps/{package_id}/v{version}",
                                "commands": [],
                            },
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )
        return path

    def test_validates_portable_oci_app(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            path = self.app_fixture(root)
            with patch.object(app_tooling, "ROOT", root):
                self.assertEqual(app_tooling.validate_app(path), 1)

    def test_unknown_language_is_allowed_with_oci_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            path = self.app_fixture(root, language="elixir")
            with patch.object(app_tooling, "ROOT", root):
                self.assertEqual(app_tooling.validate_app(path), 1)

    def test_repository_target_rejects_mutable_tag(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            path = self.app_fixture(root)
            metadata_path = path / "piphi-app.json"
            metadata = json.loads(metadata_path.read_text())
            metadata["packages"][0]["publishing"]["primary"]["repository"] = (
                "piphi-io/example:latest"
            )
            metadata_path.write_text(json.dumps(metadata), encoding="utf-8")
            with patch.object(app_tooling, "ROOT", root):
                with self.assertRaisesRegex(app_tooling.AppMetadataError, "tag or digest"):
                    app_tooling.validate_app(path)

    def test_full_oci_manifest_must_match_release_target(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            path = self.app_fixture(root)
            manifest_path = path / "manifest.json"
            manifest = json.loads(manifest_path.read_text())
            manifest["image"] = "docker.io/example/old:1.2.3"
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            with patch.object(app_tooling, "ROOT", root):
                with self.assertRaisesRegex(app_tooling.AppMetadataError, "release target"):
                    app_tooling.validate_app(path)

    def test_namespaced_release_plan_uses_immutable_package_identity(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            path = self.app_fixture(root)
            with (
                patch.object(app_tooling, "ROOT", root),
                patch.object(app_tooling, "APPS_ROOT", root / "apps"),
            ):
                plan = app_tooling.release_plan("example", "1.2.3")
            self.assertEqual(plan["tag"], "apps/example/v1.2.3")
            self.assertEqual(plan["image"], "ghcr.io/piphi-io/example")


if __name__ == "__main__":
    unittest.main()
