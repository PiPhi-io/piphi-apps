from pathlib import Path


def test_container_entrypoint_honors_runtime_port_environment() -> None:
    dockerfile = (Path(__file__).parents[1] / "Dockerfile").read_text()

    assert 'CMD ["python", "-m", "piphi_camera_stream.main"]' in dockerfile
    assert '"--port", "8090"' not in dockerfile
    assert "COPY pyproject.toml pdm.lock ./" in dockerfile
    assert "pdm export --prod" in dockerfile
    assert dockerfile.count("@sha256:") == 2
    assert "USER piphi" in dockerfile
    assert "chown -R piphi:piphi /app/data" in dockerfile
