from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_runtime_container_has_production_safety_profile() -> None:
    dockerfile = (ROOT / "Dockerfile").read_text()
    dockerignore = (ROOT / ".dockerignore").read_text().splitlines()

    assert "USER piphi" in dockerfile
    assert 'VOLUME ["/var/lib/piphi"]' in dockerfile
    assert "PIPHI_AUTOMATION_LEDGER_PATH=/var/lib/piphi/automation-actions.sqlite3" in dockerfile
    assert "HEALTHCHECK" in dockerfile
    assert "127.0.0.1:8091/health" in dockerfile
    assert "node_modules" in dockerignore
    assert ".git" in dockerignore


def test_release_image_publishes_supply_chain_metadata() -> None:
    workflow = (ROOT / ".github" / "workflows" / "release.yml").read_text()

    assert "provenance: mode=max" in workflow
    assert "sbom: true" in workflow
