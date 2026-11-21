from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_runtime_container_has_production_safety_profile() -> None:
    dockerfile = (ROOT / "Dockerfile").read_text()
    dockerignore = (ROOT / ".dockerignore").read_text().splitlines()

    assert "USER 10001:10001" in dockerfile
    assert "FROM python:3.12-slim@sha256:" in dockerfile
    assert "--require-hashes" in dockerfile
    assert 'VOLUME ["/var/lib/piphi"]' in dockerfile
    assert "PIPHI_AUTOMATION_LEDGER_PATH=/var/lib/piphi/automation-actions.sqlite3" in dockerfile
    assert "HEALTHCHECK" in dockerfile
    assert "127.0.0.1:8091/health" in dockerfile
    assert "node_modules" in dockerignore
    assert ".git" in dockerignore


def test_release_image_publishes_supply_chain_metadata() -> None:
    app = (ROOT / "piphi-app.json").read_text()
    assert '"mode": "piphi_managed"' in app
    assert '"build_container": true' in app
