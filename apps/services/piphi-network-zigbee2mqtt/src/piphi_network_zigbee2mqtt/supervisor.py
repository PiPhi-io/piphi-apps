from __future__ import annotations

import asyncio
import re
from pathlib import Path
from typing import Protocol

from .bridge_models import (
    CommandResult,
    DockerSupervisorSettings,
    Pm2SupervisorSettings,
    PrerequisiteCheckRequest,
    PrerequisiteCheckResponse,
    SupervisorAction,
    SupervisorLogsRequest,
    SupervisorRequest,
    SupervisorResponse,
)


class CommandRunner(Protocol):
    async def run(
        self,
        command: list[str],
        *,
        cwd: str | None = None,
        env: dict[str, str] | None = None,
        timeout_seconds: float = 30.0,
    ) -> CommandResult:
        ...


class AsyncioCommandRunner:
    async def run(
        self,
        command: list[str],
        *,
        cwd: str | None = None,
        env: dict[str, str] | None = None,
        timeout_seconds: float = 30.0,
    ) -> CommandResult:
        try:
            process = await asyncio.create_subprocess_exec(
                *command,
                cwd=cwd,
                env=env or None,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        except FileNotFoundError as exc:
            return CommandResult(command=command, returncode=127, stderr=str(exc))

        try:
            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=timeout_seconds)
        except TimeoutError:
            process.kill()
            stdout, _stderr = await process.communicate()
            return CommandResult(
                command=command,
                returncode=124,
                stdout=stdout.decode(errors="replace").strip(),
                stderr=f"command timed out after {timeout_seconds:g}s",
            )
        return CommandResult(
            command=command,
            returncode=int(process.returncode or 0),
            stdout=stdout.decode(errors="replace").strip(),
            stderr=stderr.decode(errors="replace").strip(),
        )


async def supervise(
    action: SupervisorAction,
    request: SupervisorRequest,
    *,
    runner: CommandRunner | None = None,
) -> SupervisorResponse:
    selected_runner = runner or AsyncioCommandRunner()
    if request.mode == "docker":
        if request.docker is None:
            return _missing_settings_response(request.mode, action, "docker settings are required")
        return await _supervise_docker(action, request.docker, request.dry_run, selected_runner)
    if request.pm2 is None:
        return _missing_settings_response(request.mode, action, "pm2 settings are required")
    return await _supervise_pm2(action, request.pm2, request.dry_run, selected_runner)


async def supervisor_logs(
    request: SupervisorLogsRequest,
    *,
    runner: CommandRunner | None = None,
) -> SupervisorResponse:
    selected_runner = runner or AsyncioCommandRunner()
    if request.mode == "docker":
        if request.docker is None:
            return _missing_settings_response(request.mode, "logs", "docker settings are required")
        command = ["docker", "logs", "--tail", str(request.tail), request.docker.container_name]
        result = await _maybe_run(command, request.dry_run, selected_runner)
        return _response("docker", "logs", "planned" if request.dry_run else "collected", [command], [result], request.dry_run or result.returncode == 0)
    if request.pm2 is None:
        return _missing_settings_response(request.mode, "logs", "pm2 settings are required")
    command = ["pm2", "logs", request.pm2.process_name, "--lines", str(request.tail), "--nostream"]
    result = await _maybe_run(command, request.dry_run, selected_runner, cwd=request.pm2.working_dir, env=request.pm2.env)
    return _response("pm2", "logs", "planned" if request.dry_run else "collected", [command], [result], request.dry_run or result.returncode == 0)


async def check_prerequisites(
    request: PrerequisiteCheckRequest,
    *,
    runner: CommandRunner | None = None,
) -> PrerequisiteCheckResponse:
    selected_runner = runner or AsyncioCommandRunner()
    if request.mode == "docker":
        command = ["docker", "version", "--format", "{{.Server.Version}}"]
        result = await _maybe_run(command, request.dry_run, selected_runner)
        checks = [_check("docker_available", request.dry_run or result.returncode == 0, command, result)]
        if request.docker is not None:
            checks.append({"name": "host_data_path_configured", "ok": bool(request.docker.host_data_path)})
            checks.append({"name": "coordinator_device_configured", "ok": bool(request.docker.device_path or request.docker.network_mode)})
        return PrerequisiteCheckResponse(ok=all(item["ok"] for item in checks), mode="docker", checks=checks)

    command = ["pm2", "ping"]
    result = await _maybe_run(command, request.dry_run, selected_runner)
    checks = [_check("pm2_available", request.dry_run or result.returncode == 0, command, result)]
    if request.pm2 is not None:
        checks.append({"name": "working_dir_configured", "ok": bool(request.pm2.working_dir)})
        checks.append({"name": "script_configured", "ok": bool(request.pm2.script)})
    return PrerequisiteCheckResponse(ok=all(item["ok"] for item in checks), mode="pm2", checks=checks)


async def _supervise_docker(
    action: SupervisorAction,
    settings: DockerSupervisorSettings,
    dry_run: bool,
    runner: CommandRunner,
) -> SupervisorResponse:
    status_command = ["docker", "inspect", "--format", "{{.State.Status}}", settings.container_name]
    if action == "status":
        result = await _maybe_run(status_command, dry_run, runner)
        status = _docker_status_from_result(result)
        return _response("docker", action, status, [status_command], [result], status != "missing")

    status_result = await _maybe_run(status_command, dry_run, runner)
    status = "missing" if dry_run else _docker_status_from_result(status_result)
    commands = [status_command]
    results = [status_result]

    if action == "start":
        command = _docker_start_command(settings) if status == "missing" else ["docker", "start", settings.container_name]
    elif action == "stop":
        command = ["docker", "stop", settings.container_name]
    else:
        command = ["docker", "restart", settings.container_name] if status != "missing" else _docker_start_command(settings)

    commands.append(command)
    result = await _maybe_run(command, dry_run, runner)
    results.append(result)
    ok = dry_run or result.returncode == 0
    return _response("docker", action, "planned" if dry_run else ("running" if ok and action != "stop" else "stopped"), commands, results, ok)


async def _supervise_pm2(
    action: SupervisorAction,
    settings: Pm2SupervisorSettings,
    dry_run: bool,
    runner: CommandRunner,
) -> SupervisorResponse:
    status_command = ["pm2", "jlist"]
    if action == "status":
        result = await _maybe_run(status_command, dry_run, runner)
        status = _pm2_status_from_result(settings.process_name, result)
        return _response("pm2", action, status, [status_command], [result], status != "missing")

    if action == "start":
        command = _pm2_start_command(settings)
    elif action == "stop":
        command = ["pm2", "stop", settings.process_name]
    else:
        command = ["pm2", "restart", settings.process_name]

    result = await _maybe_run(command, dry_run, runner, cwd=settings.working_dir, env=settings.env)
    ok = dry_run or result.returncode == 0
    status = "planned" if dry_run else ("online" if ok and action != "stop" else "stopped")
    return _response("pm2", action, status, [command], [result], ok)


def _docker_start_command(settings: DockerSupervisorSettings) -> list[str]:
    command = [
        "docker",
        "run",
        "-d",
        "--name",
        settings.container_name,
        "--restart",
        "unless-stopped",
        "-v",
        f"{settings.host_data_path}:{settings.container_data_path}",
    ]
    if settings.network_mode:
        command.extend(["--network", settings.network_mode])
    if settings.frontend_port and not settings.network_mode:
        command.extend(["-p", f"{settings.frontend_port}:8080"])
    if settings.device_path:
        container_device = settings.device_path if settings.device_path.startswith("/") else "/dev/ttyZigbee"
        command.extend(["--device", f"{settings.device_path}:{container_device}"])
    for key, value in sorted(settings.environment.items()):
        command.extend(["-e", f"{key}={value}"])
    command.append(settings.image)
    return command


def _pm2_start_command(settings: Pm2SupervisorSettings) -> list[str]:
    command = ["pm2", "start", settings.script, "--name", settings.process_name]
    if settings.interpreter:
        command.extend(["--interpreter", settings.interpreter])
    if settings.env:
        command.append("--update-env")
    return command


async def _maybe_run(
    command: list[str],
    dry_run: bool,
    runner: CommandRunner,
    *,
    cwd: str | None = None,
    env: dict[str, str] | None = None,
) -> CommandResult:
    if dry_run:
        return CommandResult(command=command, returncode=0)
    return await runner.run(command, cwd=_normalize_cwd(cwd), env=env)


def _normalize_cwd(cwd: str | None) -> str | None:
    if not cwd:
        return None
    return str(Path(cwd).expanduser())


def _docker_status_from_result(result: CommandResult) -> str:
    if result.returncode != 0:
        return "missing"
    status = result.stdout.strip()
    return status or "unknown"


def _pm2_status_from_result(process_name: str, result: CommandResult) -> str:
    if result.returncode != 0:
        return "missing"
    if process_name in result.stdout:
        if '"status":"online"' in result.stdout or '"status": "online"' in result.stdout:
            return "online"
        return "managed"
    return "missing"


def _response(
    mode: str,
    action: SupervisorAction,
    status: str,
    commands: list[list[str]],
    results: list[CommandResult],
    ok: bool,
) -> SupervisorResponse:
    safe_results = [_redact_result(result) for result in results]
    return SupervisorResponse(
        ok=ok,
        mode=mode,  # type: ignore[arg-type]
        action=action,
        status=status,
        commands=[_redact_command(command) for command in commands],
        results=safe_results,
    )


def _missing_settings_response(mode: str, action: SupervisorAction, message: str) -> SupervisorResponse:
    return SupervisorResponse(
        ok=False,
        mode=mode,  # type: ignore[arg-type]
        action=action,
        status="invalid",
        message=message,
    )


def _check(name: str, ok: bool, command: list[str], result: CommandResult) -> dict[str, object]:
    safe_result = _redact_result(result)
    return {
        "name": name,
        "ok": ok,
        "command": _redact_command(command),
        "returncode": safe_result.returncode,
        "stdout": safe_result.stdout,
        "stderr": safe_result.stderr,
    }


_SECRET_KEY_RE = re.compile(r"(pass(word)?|secret|token|key|credential)", re.IGNORECASE)
_SECRET_ASSIGNMENT_RE = re.compile(
    r"(?P<key>[A-Za-z0-9_]*(?:PASS(?:WORD)?|SECRET|TOKEN|KEY|CREDENTIAL)[A-Za-z0-9_]*)=(?P<value>[^\s]+)",
    re.IGNORECASE,
)
_SECRET_URL_RE = re.compile(r"(://[^:/\s]+:)([^@/\s]+)(@)")


def _redact_command(command: list[str]) -> list[str]:
    redacted: list[str] = []
    redact_next = False
    for token in command:
        if redact_next:
            redacted.append("[redacted]")
            redact_next = False
            continue
        if token in {"--password", "--token", "--secret", "--api-key"}:
            redacted.append(token)
            redact_next = True
            continue
        redacted.append(_redact_text(token))
    return redacted


def _redact_result(result: CommandResult) -> CommandResult:
    return result.model_copy(
        update={
            "command": _redact_command(result.command),
            "stdout": _redact_text(result.stdout),
            "stderr": _redact_text(result.stderr),
        }
    )


def _redact_text(value: str) -> str:
    text = _SECRET_URL_RE.sub(r"\1[redacted]\3", value)

    def replace_assignment(match: re.Match[str]) -> str:
        key = match.group("key")
        if _SECRET_KEY_RE.search(key):
            return f"{key}=[redacted]"
        return match.group(0)

    return _SECRET_ASSIGNMENT_RE.sub(replace_assignment, text)
