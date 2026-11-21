from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_container_pins_base_upstream_source_and_python_dependencies() -> None:
    dockerfile = (ROOT / "Dockerfile").read_text()
    assert dockerfile.count("python:3.12-slim-bookworm@sha256:") == 3
    assert "ADD --checksum=sha256:" in dockerfile
    assert "RTL433_UPSTREAM_REVISION=f15b67699e902522014e7593d060ad37410eda00" in dockerfile
    assert "--require-hashes" in dockerfile
    assert "org.opencontainers.image.revision" in dockerfile


def test_container_is_non_root_health_checked_and_stateful() -> None:
    dockerfile = (ROOT / "Dockerfile").read_text()
    assert "useradd --system --uid 10001" in dockerfile
    assert "USER rtl433" in dockerfile
    assert 'VOLUME ["/var/lib/piphi"]' in dockerfile
    assert "HEALTHCHECK" in dockerfile
    assert "data['status'] == 'ok'" in dockerfile
