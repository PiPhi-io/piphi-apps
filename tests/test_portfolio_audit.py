from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import build_portfolio_audit


class PortfolioAuditTests(unittest.TestCase):
    def test_immutable_image_replaces_tag(self) -> None:
        self.assertEqual(
            build_portfolio_audit.immutable_image(
                "ghcr.io/piphi-io/example:1.2.3", "sha256:abc"
            ),
            "ghcr.io/piphi-io/example@sha256:abc",
        )
        self.assertEqual(
            build_portfolio_audit.immutable_image(
                "registry.example:5000/piphi/example:1.2.3", "sha256:def"
            ),
            "registry.example:5000/piphi/example@sha256:def",
        )

    def test_discovers_source_package_contract(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "apps"
            app = root / "integrations" / "example"
            app.mkdir(parents=True)
            (app / "manifest.json").write_text(
                json.dumps(
                    {
                        "id": "example",
                        "version": "1.2.3",
                        "image": "ghcr.io/piphi-io/example:1.2.3",
                    }
                ),
                encoding="utf-8",
            )
            (app / "piphi-app.json").write_text(
                json.dumps(
                    {
                        "source": {"imported_from": None},
                        "ci": {
                            "enforcement": "full",
                            "build_container": True,
                            "commands": ["pytest"],
                        },
                        "packages": [
                            {
                                "id": "example",
                                "type": "integration",
                                "version": "1.2.3",
                                "manifest": "manifest.json",
                                "artifact": {
                                    "kind": "oci",
                                    "platforms": ["linux/amd64", "linux/arm64"],
                                },
                                "publishing": {
                                    "mode": "piphi_managed",
                                    "primary": {
                                        "registry": "ghcr.io",
                                        "repository": "piphi-io/example",
                                    },
                                },
                                "release": {
                                    "tag": "apps/{package_id}/v{version}"
                                },
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )

            packages = build_portfolio_audit.discover_packages(root)

        self.assertEqual(packages["example"]["folder"], "apps/integrations/example")
        self.assertEqual(
            packages["example"]["manifest_image"],
            "ghcr.io/piphi-io/example:1.2.3",
        )

    def test_requires_comparator_for_every_in_scope_package(self) -> None:
        package = {
            "id": "example",
            "type": "integration",
            "folder": "apps/integrations/example",
            "source_version": "1.2.3",
            "manifest_path": "manifest.json",
            "manifest_image": "ghcr.io/piphi-io/example:1.2.3",
            "imported_from": None,
            "ci_enforcement": "full",
            "ci_build_container": True,
            "ci_commands": ["pytest"],
            "artifact_kind": "oci",
            "platforms": ["linux/amd64", "linux/arm64"],
            "publishing_mode": "piphi_managed",
            "publishing_target": {
                "registry": "ghcr.io",
                "repository": "piphi-io/example",
            },
            "release_tag": "apps/example/v1.2.3",
        }
        registry = [
            {
                "id": "example",
                "type": "integration",
                "owner": "PiPhi-io",
                "version": "1.2.3",
                "image": "ghcr.io/piphi-io/example:1.2.3",
                "marketplace": {"governance": {}},
            }
        ]
        with self.assertRaisesRegex(
            build_portfolio_audit.PortfolioAuditError, "has no HA comparator"
        ):
            build_portfolio_audit.build_inventory(
                {"example": package},
                registry,
                {"comparators": {}},
                source_revision="source",
                registry_revision="registry",
                tags=set(),
            )

    def test_external_output_path_can_be_displayed(self) -> None:
        output = Path("/tmp/opencode/portfolio-inventory.json")
        self.assertEqual(build_portfolio_audit.display_path(output), output)


if __name__ == "__main__":
    unittest.main()
