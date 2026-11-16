from __future__ import annotations

import pytest

from piphi_network_zigbee2mqtt.bridge_models import (
    CommandResult,
    DockerSupervisorSettings,
    Pm2SupervisorSettings,
    PrerequisiteCheckRequest,
    SupervisorLogsRequest,
    SupervisorRequest,
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
async def test_docker_lifecycle_is_delegated_to_core_without_host_commands() -> None:
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
    assert result.status == "managed_by_core"
    assert result.commands == []
    assert runner.calls == []


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
async def test_supervisor_logs_for_docker_are_delegated_to_core() -> None:
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
    assert result.commands == []
    assert result.results == []
    assert runner.calls == []


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
async def test_docker_supervisor_ignores_caller_environment_and_output() -> None:
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
                environment={"TZ": "UTC"},
            ),
        ),
        runner=runner,
    )

    assert result.ok is True
    assert result.commands == []
    assert result.results == []
    assert runner.calls == []


@pytest.mark.parametrize(
    "settings",
    [
        {"host_data_path": "/var/lib/piphi/zigbee2mqtt", "image": "attacker/image:latest"},
        {"host_data_path": "/var/lib/piphi/zigbee2mqtt", "network_mode": "host"},
        {"host_data_path": "/var/lib/piphi/zigbee2mqtt", "environment": {"LD_PRELOAD": "/tmp/x"}},
        {"host_data_path": "/var/lib/piphi/zigbee2mqtt", "device_path": "/dev/tty/../../etc/passwd"},
    ],
)
def test_docker_supervisor_rejects_caller_controlled_runtime_options(settings) -> None:
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        DockerSupervisorSettings(**settings)
