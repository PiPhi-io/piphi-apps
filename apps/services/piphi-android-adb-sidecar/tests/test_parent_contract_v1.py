from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from piphi_android_adb_sidecar.parent_contract_v1 import (
    CONTRACT_VERSION,
    MAX_PAYLOAD_BYTES,
    AcceptedResponse,
    CompletedResponse,
    ContractPayloadError,
    ErrorCode,
    ErrorResponse,
    KeyCode,
    KeyEvent,
    KeyEventResult,
    PropertyQuery,
    PropertyQueryResult,
    ReadableProperty,
    parse_request,
    response_adapter,
)


def request_payload(command: dict[str, object]) -> bytes:
    return json.dumps(
        {
            "version": CONTRACT_VERSION,
            "request_id": "request-1",
            "target": {"target_id": "target-living-room-tv"},
            "timeout_ms": 5_000,
            "command": command,
        }
    ).encode()


def test_parses_allowlisted_key_event_for_one_target() -> None:
    request = parse_request(
        request_payload({"operation": "key_event", "key": "home", "repeat": 2})
    )

    assert request.target.target_id == "target-living-room-tv"
    assert request.command == KeyEvent(operation="key_event", key=KeyCode.HOME, repeat=2)


def test_parses_bounded_allowlisted_property_query() -> None:
    request = parse_request(
        request_payload(
            {
                "operation": "property_query",
                "properties": ["ro.product.model", "ro.build.version.sdk"],
            }
        )
    )

    assert request.command == PropertyQuery(
        operation="property_query",
        properties=[ReadableProperty.PRODUCT_MODEL, ReadableProperty.ANDROID_SDK],
    )


@pytest.mark.parametrize(
    "mutation",
    [
        {"target": None},
        {"target": {}},
        {"target": {"target_id": "device-1", "host": "device-2"}},
        {"targets": [{"target_id": "device-1"}]},
    ],
)
def test_rejects_missing_ambiguous_or_multiple_targets(mutation: dict[str, object]) -> None:
    value = json.loads(request_payload({"operation": "key_event", "key": "back"}))
    value.pop("target", None)
    value.update(mutation)

    with pytest.raises(ValidationError):
        parse_request(json.dumps(value))


@pytest.mark.parametrize(
    "command",
    [
        {"operation": "shell", "command": "id"},
        {"operation": "intent", "action": "android.intent.action.VIEW"},
        {"operation": "file_push", "path": "/data/local/tmp/x"},
        {"operation": "package_install", "package": "app.apk"},
        {"operation": "forward", "local": "tcp:8000", "remote": "tcp:8000"},
        {"operation": "app_launch", "package": "com.example.app"},
    ],
)
def test_rejects_unbounded_or_unsupported_operations(command: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        parse_request(request_payload(command))


def test_rejects_non_allowlisted_key_and_property() -> None:
    with pytest.raises(ValidationError):
        parse_request(request_payload({"operation": "key_event", "key": "power"}))

    with pytest.raises(ValidationError):
        parse_request(
            request_payload(
                {"operation": "property_query", "properties": ["persist.secret.value"]}
            )
        )


@pytest.mark.parametrize(
    "command",
    [
        {"operation": "key_event", "key": "home", "repeat": 0},
        {"operation": "key_event", "key": "home", "repeat": 11},
        {"operation": "key_event", "key": "home", "repeat": "2"},
        {"operation": "property_query", "properties": []},
        {
            "operation": "property_query",
            "properties": ["ro.product.model"] * 9,
        },
        {
            "operation": "property_query",
            "properties": ["ro.product.model", "ro.product.model"],
        },
    ],
)
def test_enforces_scalar_and_list_bounds(command: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        parse_request(request_payload(command))


def test_rejects_extra_fields_wrong_version_and_out_of_range_timeout() -> None:
    value = json.loads(request_payload({"operation": "key_event", "key": "enter"}))
    value["raw_shell"] = "id"
    with pytest.raises(ValidationError):
        parse_request(json.dumps(value))

    value.pop("raw_shell")
    value["version"] = "2"
    with pytest.raises(ValidationError):
        parse_request(json.dumps(value))

    value["version"] = CONTRACT_VERSION
    value["timeout_ms"] = 30_001
    with pytest.raises(ValidationError):
        parse_request(json.dumps(value))


def test_rejects_unsafe_payload_envelopes() -> None:
    with pytest.raises(ContractPayloadError, match="byte limit"):
        parse_request(b" " * (MAX_PAYLOAD_BYTES + 1))
    with pytest.raises(ContractPayloadError, match="UTF-8"):
        parse_request(b"\xff")
    with pytest.raises(ContractPayloadError, match="JSON object"):
        parse_request("[]")
    with pytest.raises(ContractPayloadError, match="duplicate field"):
        parse_request(
            '{"version":"1","version":"1","request_id":"x","target":{},'
            '"timeout_ms":100,"command":{}}'
        )


def test_response_contract_has_only_explicit_errors() -> None:
    expected = {
        "unauthorized",
        "offline",
        "timeout",
        "queue_full",
        "unsupported",
    }
    assert {code.value for code in ErrorCode} == expected

    response = response_adapter.validate_python(
        {
            "version": "1",
            "request_id": "request-1",
            "status": "error",
            "error": "queue_full",
            "message": "command queue is full",
            "retry_after_ms": 250,
        }
    )
    assert response == ErrorResponse(
        version="1",
        request_id="request-1",
        status="error",
        error=ErrorCode.QUEUE_FULL,
        message="command queue is full",
        retry_after_ms=250,
    )

    assert AcceptedResponse(
        version="1", request_id="request-1", status="accepted"
    ).status == "accepted"
    completed = response_adapter.validate_python(
        {
            "version": "1",
            "request_id": "request-1",
            "status": "completed",
            "result": {
                "operation": "property_query",
                "properties": {"ro.product.model": "Example TV"},
            },
        }
    )
    assert completed == CompletedResponse(
        version="1",
        request_id="request-1",
        status="completed",
        result=PropertyQueryResult(
            operation="property_query",
            properties={ReadableProperty.PRODUCT_MODEL: "Example TV"},
        ),
    )
    assert CompletedResponse(
        version="1",
        request_id="request-2",
        status="completed",
        result=KeyEventResult(operation="key_event", repeats_completed=1),
    ).status == "completed"
    with pytest.raises(ValidationError):
        ErrorResponse(
            version="1",
            request_id="request-1",
            status="error",
            error="internal_error",  # type: ignore[arg-type]
            message="not part of the public contract",
        )
