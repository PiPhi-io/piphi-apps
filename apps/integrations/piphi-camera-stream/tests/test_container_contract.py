from pathlib import Path


def test_container_entrypoint_honors_runtime_port_environment() -> None:
    dockerfile = (Path(__file__).parents[1] / "Dockerfile").read_text()

    assert 'CMD ["python", "-m", "piphi_camera_stream.main"]' in dockerfile
    assert '"--port", "8090"' not in dockerfile
