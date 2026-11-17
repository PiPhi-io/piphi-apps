from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_container_has_immutable_labels_and_non_root_runtime() -> None:
    dockerfile = (ROOT / "Dockerfile").read_text()

    assert 'org.opencontainers.image.source="${SOURCE_REPOSITORY}"' in dockerfile
    assert 'org.opencontainers.image.revision="${SOURCE_REVISION}"' in dockerfile
    assert 'org.opencontainers.image.version="${RELEASE_VERSION}"' in dockerfile
    assert "useradd --system --uid 10001" in dockerfile
    assert "USER piphi" in dockerfile
    assert 'VOLUME ["/data/piphi"]' in dockerfile
