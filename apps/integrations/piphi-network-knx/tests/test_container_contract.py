from pathlib import Path

ROOT = Path(__file__).parents[1]


def test_container_declares_release_provenance() -> None:
    dockerfile = (ROOT / "Dockerfile").read_text()

    assert 'org.opencontainers.image.source="${SOURCE_REPOSITORY}"' in dockerfile
    assert 'org.opencontainers.image.revision="${SOURCE_REVISION}"' in dockerfile
    assert 'org.opencontainers.image.version="${RELEASE_VERSION}"' in dockerfile


def test_container_declares_non_root_writable_state() -> None:
    dockerfile = (ROOT / "Dockerfile").read_text()

    assert "useradd --create-home --uid 10001 piphi" in dockerfile
    assert "chown -R piphi:piphi /app" in dockerfile
    assert 'VOLUME ["/app/data"]' in dockerfile
    assert "USER piphi" in dockerfile
