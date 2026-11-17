import json
from pathlib import Path


def test_container_entrypoint_honors_runtime_port_environment() -> None:
    dockerfile = (Path(__file__).parents[1] / "Dockerfile").read_text()

    assert 'CMD ["python", "-m", "piphi_camera_stream.main"]' in dockerfile
    assert '"--port", "8090"' not in dockerfile
    assert "COPY pyproject.toml pdm.lock ./" in dockerfile
    assert "pdm export --prod" in dockerfile
    assert dockerfile.count("@sha256:") == 2
    assert "USER piphi" in dockerfile
    assert "chown -R piphi:piphi /data/piphi" in dockerfile


def test_container_declares_release_provenance() -> None:
    dockerfile = (Path(__file__).parents[1] / "Dockerfile").read_text()

    assert 'org.opencontainers.image.source="${SOURCE_REPOSITORY}"' in dockerfile
    assert 'org.opencontainers.image.revision="${SOURCE_REVISION}"' in dockerfile
    assert 'org.opencontainers.image.version="${RELEASE_VERSION}"' in dockerfile


def test_container_declares_non_root_writable_ledger() -> None:
    root = Path(__file__).parents[1]
    dockerfile = (root / "Dockerfile").read_text()
    manifest = json.loads((root / "manifest.json").read_text())
    container = manifest["runtime"]["linux"]["container"]

    assert 'VOLUME ["/data/piphi"]' in dockerfile
    assert container["environment"]["PIPHI_AUTOMATION_LEDGER_PATH"].startswith("/data/piphi/")
    assert container["volumes"] == [
        {
            "host": "/var/lib/piphi/camera-stream",
            "container": "/data/piphi",
            "mode": "rw",
        }
    ]
