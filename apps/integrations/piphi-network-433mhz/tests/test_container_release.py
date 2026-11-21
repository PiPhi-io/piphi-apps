from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_container_is_pinned_hash_locked_non_root_and_stateful() -> None:
    dockerfile = (ROOT / "Dockerfile").read_text()
    assert "FROM python:3.12-slim@sha256:" in dockerfile
    assert "--require-hashes" in dockerfile
    assert "USER 10001:10001" in dockerfile
    assert 'VOLUME ["/var/lib/piphi"]' in dockerfile
    assert "HEALTHCHECK" in dockerfile
    assert "org.opencontainers.image.revision" in dockerfile


def test_manifest_uses_durable_runtime_paths() -> None:
    manifest = (ROOT / "src/manifest.json").read_text()
    assert "/var/lib/piphi/discovery.json" in manifest
    assert "/var/lib/piphi/automation-actions.sqlite3" in manifest
    assert '"mode": "rw"' in manifest
