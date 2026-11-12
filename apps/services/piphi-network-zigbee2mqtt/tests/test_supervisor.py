from __future__ import annotations

import pytest

from piphi_network_zigbee2mqtt.bridge_models import (
    CommandResult,
    DockerSupervisorSettings,
    Pm2SupervisorSettings,
    PrerequisiteCheckRequest,
    SupervisorRequest,
    SupervisorLogsRequest,
)
from piphi_network_zigbee2mqtt.broker_health import parse_mqtt_endpoint
from piphi_network_zigbee2mqtt.supervisor import check_prerequisites, supervise, supervisor_logs


class FakeRunner:
    def __init__(self, responses: list[CommandResult] | None = None) -> None:
        self.responses = list(responses or [])
        self.calls: list[dict[str, object]] = []

    async def run(self, command: list[str], *, cwd: str | None = None, env: dict[str, str] | None = None):
        self.calls.append({"command": command, "cwd": cwd, "env": env})
        if self.responses:
            return self.responses.pop(0)
        return CommandResult(command=command, returncode=0)


@pytest.mark.anyio
async def test_docker_start_runs_container_when_missing() -> None:
    runner = FakeRunner(
        [
            CommandResult(command=["docker", "inspect"], returncode=1, stderr="No such object"),
            CommandResult(command=["docker", "run"], returncode=0, stdout="container-id"),
        ]
    )

    result = await supervise(
        "start",
        SupervisorRequest(
            mode="docker",
            docker=DockerSupervisorSettings(
                host_data_path="/var/lib/piphi/zigbee2mqtt",
                device_path="/dev/ttyUSB0",
                frontend_port=8080,
            ),
        ),
        runner=runner,
    )

    assert result.ok is True
    assert result.commands[0][:2] == ["docker", "inspect"]
    run_command = result.commands[1]
    assert run_command[:3] == ["docker", "run", "-d"]
    assert "ghcr.io/koenkk/zigbee2mqtt:latest" in run_command
    assert "--device" in run_command
    assert "/dev/ttyUSB0:/dev/ttyUSB0" in run_command


@pytest.mark.anyio
async def test_pm2_restart_uses_working_directory_and_env() -> None:
    runner = FakeRunner([CommandResult(command=["pm2", "restart"], returncode=0)])

    result = await supervise(
        "restart",
        SupervisorRequest(
            mode="pm2",
            pm2=Pm2SupervisorSettings(
                process_name="piphi-zigbee2mqtt",
                working_dir="/opt/zigbee2mqtt",
                env={"ZIGBEE2MQTT_DATA": "/var/lib/piphi/zigbee2mqtt"},
            ),
        ),
        runner=runner,
    )

    assert result.ok is True
    assert result.commands == [["pm2", "restart", "piphi-zigbee2mqtt"]]
    assert runner.calls[0]["cwd"] == "/opt/zigbee2mqtt"
    assert runner.calls[0]["env"] == {"ZIGBEE2MQTT_DATA": "/var/lib/piphi/zigbee2mqtt"}


@pytest.mark.anyio
async def test_supervisor_logs_for_docker() -> None:
    runner = FakeRunner([CommandResult(command=["docker", "logs"], returncode=0, stdout="ready")])

    result = await supervisor_logs(
        SupervisorLogsRequest(
            mode="docker",
            tail=50,
            docker=DockerSupervisorSettings(host_data_path="/var/lib/piphi/zigbee2mqtt"),
        ),
        runner=runner,
    )

    assert result.ok is True
    assert result.action == "logs"
    assert result.commands == [["docker", "logs", "--tail", "50", "piphi-zigbee2mqtt"]]
    assert result.results[0].stdout == "ready"


def test_parse_mqtt_endpoint_defaults_ports() -> None:
    assert parse_mqtt_endpoint("broker.local") == ("broker.local", 1883)
    assert parse_mqtt_endpoint("mqtt://broker.local:1884") == ("broker.local", 1884)
    assert parse_mqtt_endpoint("mqtts://broker.local") == ("broker.local", 8883)


@pytest.mark.anyio
async def test_prerequisite_checks_report_pm2_availability() -> None:
    runner = FakeRunner([CommandResult(command=["pm2", "ping"], returncode=0, stdout="pong")])

    result = await check_prerequisites(
        PrerequisiteCheckRequest(
            mode="pm2",
            pm2=Pm2SupervisorSettings(working_dir="/opt/zigbee2mqtt"),
        ),
        runner=runner,
    )

    assert result.ok is True
    assert result.checks[0]["name"] == "pm2_available"


@pytest.mark.anyio
async def test_supervisor_response_redacts_secret_values() -> None:
    runner = FakeRunner(
        [
            CommandResult(command=["docker", "inspect"], returncode=1, stderr="No such object"),
            CommandResult(
                command=["docker", "run"],
                returncode=0,
                stdout="MQTT_PASSWORD=super-secret mqtt://user:secret@broker.local",
            ),
        ]
    )

    result = await supervise(
        "start",
        SupervisorRequest(
            mode="docker",
            docker=DockerSupervisorSettings(
                host_data_path="/var/lib/piphi/zigbee2mqtt",
                environment={"MQTT_PASSWORD": "super-secret"},
            ),
        ),
        runner=runner,
    )

    assert result.ok is True
    assert "MQTT_PASSWORD=[redacted]" in result.commands[1]
    assert "super-secret" not in result.results[1].stdout
    assert "mqtt://user:[redacted]@broker.local" in result.results[1].stdout
