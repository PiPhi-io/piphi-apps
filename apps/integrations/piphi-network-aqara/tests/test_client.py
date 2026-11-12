from __future__ import annotations

import httpx
import pytest

from piphi_network_aqara.cloud.client import (
    AqaraCloudAuthError,
    AqaraCloudClient,
    AqaraCloudRateLimitError,
    AqaraCloudRequestError,
)
from piphi_network_aqara.cloud.models import AqaraCloudCredentials


def build_credentials(**overrides) -> AqaraCloudCredentials:
    base = {
        "region": "us",
        "app_id": "app-id-1",
        "key_id": "key-id-1",
        "app_key": "app-key-1",
        "access_token": "access-token-1",
        "open_id": "open-id-1",
        "refresh_token": "refresh-token-1",
    }
    base.update(overrides)
    return AqaraCloudCredentials(**base)


@pytest.mark.asyncio
async def test_list_devices_and_resource_reads_are_signed() -> None:
    seen_headers: list[dict[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen_headers.append({key.lower(): value for key, value in request.headers.items()})
        payload = request.read().decode("utf-8")
        if '"intent":"query.device.info"' in payload.replace(" ", ""):
            return httpx.Response(
                200,
                json={
                    "code": 0,
                    "message": "Success",
                    "requestId": "req-1",
                    "result": {
                        "totalCount": 1,
                        "data": [
                            {
                                "did": "lumi.1234",
                                "model": "lumi.sensor_ht.agl02",
                                "deviceName": "Hallway Sensor",
                                "state": 1,
                            }
                        ],
                    },
                },
            )
        if '"intent":"query.resource.info"' in payload.replace(" ", ""):
            return httpx.Response(
                200,
                json={
                    "code": 0,
                    "message": "Success",
                    "requestId": "req-2",
                    "result": [
                        {
                            "resourceId": "0.1.85",
                            "name": "Temperature value",
                            "description": "Temperature value",
                            "access": 3,
                            "model": "lumi.sensor_ht.agl02",
                        }
                    ],
                },
            )
        if '"intent":"query.resource.value"' in payload.replace(" ", ""):
            return httpx.Response(
                200,
                json={
                    "code": 0,
                    "message": "Success",
                    "requestId": "req-3",
                    "result": [
                        {
                            "subjectId": "lumi.1234",
                            "resourceId": "0.1.85",
                            "value": "22.5",
                            "timeStamp": 1710000000000,
                        }
                    ],
                },
            )
        raise AssertionError(f"Unexpected payload: {payload}")

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as http_client:
        client = AqaraCloudClient(http_client=http_client)
        credentials = build_credentials()
        devices = await client.list_devices(credentials)
        resources = await client.resource_info(credentials, model="lumi.sensor_ht.agl02")
        values = await client.resource_values(credentials, subject_id="lumi.1234")

    assert devices[0].did == "lumi.1234"
    assert resources[0].resource_id == "0.1.85"
    assert values[0].value == "22.5"
    assert all("appid" in headers and "keyid" in headers and "sign" in headers for headers in seen_headers)
    assert all(headers.get("accesstoken") == "access-token-1" for headers in seen_headers)


@pytest.mark.asyncio
async def test_auth_intents_omit_access_token_header() -> None:
    seen_headers: list[dict[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen_headers.append({key.lower(): value for key, value in request.headers.items()})
        return httpx.Response(
            200,
            json={
                "code": 0,
                "message": "Success",
                "requestId": "req-auth",
                "result": {
                    "accessToken": "access-token-2",
                    "refreshToken": "refresh-token-2",
                    "openId": "open-id-2",
                    "expiresIn": "86400",
                },
            },
        )

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as http_client:
        client = AqaraCloudClient(http_client=http_client)
        credentials = build_credentials()
        await client.exchange_token(credentials, account="test@example.com", auth_code="123456")

    assert len(seen_headers) == 1
    assert "accesstoken" not in seen_headers[0]
    assert seen_headers[0]["appid"] == "app-id-1"


@pytest.mark.asyncio
async def test_exchange_and_refresh_token_support_auth_payloads() -> None:
    intents: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        payload = request.read().decode("utf-8").replace(" ", "")
        if '"intent":"config.auth.getToken"' in payload:
            intents.append("getToken")
            return httpx.Response(
                200,
                json={
                    "code": 0,
                    "message": "Success",
                    "requestId": "req-auth-1",
                    "result": {
                        "accessToken": "access-token-2",
                        "refreshToken": "refresh-token-2",
                        "openId": "open-id-2",
                        "expiresIn": "86400",
                    },
                },
            )
        if '"intent":"config.auth.refreshToken"' in payload:
            intents.append("refreshToken")
            return httpx.Response(
                200,
                json={
                    "code": 0,
                    "message": "Success",
                    "requestId": "req-auth-2",
                    "result": {
                        "accessToken": "access-token-3",
                        "refreshToken": "refresh-token-3",
                        "openId": "open-id-3",
                        "expiresIn": "86400",
                    },
                },
            )
        raise AssertionError(f"Unexpected payload: {payload}")

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as http_client:
        client = AqaraCloudClient(http_client=http_client)
        credentials = build_credentials()
        token_result = await client.exchange_token(credentials, account="test@example.com", auth_code="123456")
        refresh_result = await client.refresh_access_token(credentials)

    assert intents == ["getToken", "refreshToken"]
    assert token_result.access_token == "access-token-2"
    assert token_result.open_id == "open-id-2"
    assert refresh_result.access_token == "access-token-3"
    assert refresh_result.refresh_token == "refresh-token-3"


@pytest.mark.asyncio
async def test_subscribe_and_unsubscribe_resources_use_expected_intents() -> None:
    intents: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        payload = request.read().decode("utf-8").replace(" ", "")
        if '"intent":"config.resource.subscribe"' in payload:
            intents.append("subscribe")
        elif '"intent":"config.resource.unsubscribe"' in payload:
            intents.append("unsubscribe")
        else:
            raise AssertionError(f"Unexpected payload: {payload}")
        return httpx.Response(200, json={"code": 0, "message": "Success", "requestId": "req-sub", "result": None})

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as http_client:
        client = AqaraCloudClient(http_client=http_client)
        credentials = build_credentials()
        resources = [{"subjectId": "lumi.1234", "resourceIds": ["4.1.85"], "attach": "cfg-1"}]
        await client.subscribe_resources(credentials, resources=resources)
        await client.unsubscribe_resources(credentials, resources=[{"subjectId": "lumi.1234", "resourceIds": ["4.1.85"]}])

    assert intents == ["subscribe", "unsubscribe"]


@pytest.mark.asyncio
async def test_refresh_requires_refresh_token() -> None:
    client = AqaraCloudClient(http_client=httpx.AsyncClient(transport=httpx.MockTransport(lambda _request: httpx.Response(200))))
    with pytest.raises(AqaraCloudAuthError):
        await client.refresh_access_token(build_credentials(refresh_token=None))


def test_base_url_uses_region_mapping_and_custom_domain() -> None:
    client = AqaraCloudClient(http_client=httpx.AsyncClient(transport=httpx.MockTransport(lambda _request: httpx.Response(200))))
    assert client._base_url(build_credentials(region="us")) == "https://open-usa.aqara.com"
    assert client._base_url(build_credentials(custom_api_domain="api.example.test")) == "https://api.example.test"
    assert client._base_url(build_credentials(custom_api_domain="https://api.example.test")) == "https://api.example.test"


def test_base_url_rejects_unknown_region_without_custom_domain() -> None:
    client = AqaraCloudClient(http_client=httpx.AsyncClient(transport=httpx.MockTransport(lambda _request: httpx.Response(200))))
    with pytest.raises(AqaraCloudRequestError):
        client._base_url(build_credentials(region="moon"))


@pytest.mark.asyncio
async def test_list_devices_handles_pagination() -> None:
    seen_pages: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        payload = request.read().decode("utf-8").replace(" ", "")
        if '"pageNum":1' in payload:
            seen_pages.append(1)
            return httpx.Response(
                200,
                json={
                    "code": 0,
                    "message": "Success",
                    "requestId": "req-page-1",
                    "result": {
                        "totalCount": 2,
                        "data": [
                            {"did": "lumi.1", "model": "lumi.sensor_ht.agl02", "deviceName": "One", "state": 1},
                        ],
                    },
                },
            )
        if '"pageNum":2' in payload:
            seen_pages.append(2)
            return httpx.Response(
                200,
                json={
                    "code": 0,
                    "message": "Success",
                    "requestId": "req-page-2",
                    "result": {
                        "totalCount": 2,
                        "data": [
                            {"did": "lumi.2", "model": "lumi.motion.ac02", "deviceName": "Two", "state": 1},
                        ],
                    },
                },
            )
        raise AssertionError(f"Unexpected payload: {payload}")

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as http_client:
        client = AqaraCloudClient(http_client=http_client)
        devices = await client.list_devices(build_credentials())

    assert seen_pages == [1, 2]
    assert [device.did for device in devices] == ["lumi.1", "lumi.2"]


@pytest.mark.asyncio
async def test_list_devices_skips_invalid_records_and_handles_missing_total_count() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "code": 0,
                "message": "Success",
                "requestId": "req-devices-1",
                "result": {
                    "data": [
                        {"deviceName": "Missing did"},
                        "not-an-object",
                        {"did": "lumi.good", "model": "lumi.sensor_ht.agl02", "deviceName": "Good"},
                    ],
                },
            },
        )

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as http_client:
        client = AqaraCloudClient(http_client=http_client)
        devices = await client.list_devices(build_credentials())

    assert len(devices) == 1
    assert devices[0].did == "lumi.good"
    assert devices[0].name == "Good"


@pytest.mark.asyncio
async def test_list_devices_rejects_unexpected_result_shape() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"code": 0, "message": "Success", "result": ["not-a-dict"]})

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as http_client:
        client = AqaraCloudClient(http_client=http_client)
        with pytest.raises(AqaraCloudRequestError):
            await client.list_devices(build_credentials())


@pytest.mark.asyncio
async def test_resource_info_maps_full_metadata_shape() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "code": 0,
                "message": "Success",
                "requestId": "req-resource-1",
                "result": [
                    {
                        "resourceId": "14.7.111",
                        "name": "Curtain position",
                        "description": "Curtain position",
                        "access": 5,
                        "unit": 1,
                        "enums": "0,100",
                        "defaultValue": "0",
                        "minValue": 0,
                        "maxValue": 100,
                        "model": "lumi.curtain.acn002",
                    }
                ],
            },
        )

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as http_client:
        client = AqaraCloudClient(http_client=http_client)
        resources = await client.resource_info(build_credentials(), model="lumi.curtain.acn002")

    resource = resources[0]
    assert resource.resource_id == "14.7.111"
    assert resource.is_readable is True
    assert resource.is_writable is True
    assert resource.min_value == 0
    assert resource.max_value == 100
    assert resource.default_value == "0"


@pytest.mark.asyncio
async def test_resource_info_uses_cache_for_same_region_and_model() -> None:
    calls = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(
            200,
            json={
                "code": 0,
                "message": "Success",
                "requestId": "req-cache-1",
                "result": [
                    {"resourceId": "0.1.85", "name": "Temperature value", "access": 3, "model": "lumi.sensor_ht.agl02"},
                ],
            },
        )

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as http_client:
        client = AqaraCloudClient(http_client=http_client)
        credentials = build_credentials()
        first = await client.resource_info(credentials, model="lumi.sensor_ht.agl02")
        second = await client.resource_info(credentials, model="lumi.sensor_ht.agl02")

    assert calls == 1
    assert first[0].resource_id == second[0].resource_id


@pytest.mark.asyncio
async def test_resource_info_rejects_unexpected_result_shape() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"code": 0, "message": "Success", "result": {"resourceId": "0.1.85"}})

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as http_client:
        client = AqaraCloudClient(http_client=http_client)
        with pytest.raises(AqaraCloudRequestError):
            await client.resource_info(build_credentials(), model="lumi.sensor_ht.agl02")


@pytest.mark.asyncio
async def test_resource_values_filters_non_matching_subjects_and_invalid_rows() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "code": 0,
                "message": "Success",
                "requestId": "req-values-1",
                "result": [
                    {"subjectId": "someone-else", "resourceId": "0.1.85", "value": "21.5", "timeStamp": 1710000000000},
                    "not-an-object",
                    {"subjectId": "lumi.1234", "value": "21.5", "timeStamp": 1710000000000},
                    {"subjectId": "lumi.1234", "resourceId": "0.1.85", "value": "21.5", "timeStamp": 1710000000000},
                ],
            },
        )

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as http_client:
        client = AqaraCloudClient(http_client=http_client)
        values = await client.resource_values(build_credentials(), subject_id="lumi.1234")

    assert len(values) == 1
    assert values[0].subject_id == "lumi.1234"
    assert values[0].resource_id == "0.1.85"


@pytest.mark.asyncio
async def test_resource_values_rejects_unexpected_result_shape() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"code": 0, "message": "Success", "result": {"subjectId": "lumi.1234"}})

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as http_client:
        client = AqaraCloudClient(http_client=http_client)
        with pytest.raises(AqaraCloudRequestError):
            await client.resource_values(build_credentials(), subject_id="lumi.1234")


@pytest.mark.asyncio
async def test_write_resource_sends_expected_payload() -> None:
    payloads: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        payloads.append(request.read().decode("utf-8").replace(" ", ""))
        return httpx.Response(200, json={"code": 0, "message": "Success", "result": None})

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as http_client:
        client = AqaraCloudClient(http_client=http_client)
        await client.write_resource(build_credentials(), subject_id="lumi.1234", resource_id="4.1.85", value="1")

    assert len(payloads) == 1
    assert '"intent":"write.resource.device"' in payloads[0]
    assert '"subjectId":"lumi.1234"' in payloads[0]
    assert '"resourceId":"4.1.85"' in payloads[0]
    assert '"value":"1"' in payloads[0]


@pytest.mark.asyncio
@pytest.mark.parametrize("status_code", [401, 403])
async def test_request_maps_http_auth_statuses_to_auth_error(status_code: int) -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(status_code, text="denied")

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as http_client:
        client = AqaraCloudClient(http_client=http_client)
        with pytest.raises(AqaraCloudAuthError):
            await client.list_devices(build_credentials())


@pytest.mark.asyncio
async def test_request_maps_http_4xx_to_request_error() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, text="bad request")

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as http_client:
        client = AqaraCloudClient(http_client=http_client)
        with pytest.raises(AqaraCloudRequestError):
            await client.list_devices(build_credentials())


@pytest.mark.asyncio
async def test_request_classifies_auth_error_from_api_code() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "code": 401,
                "message": "accessToken invalid",
                "requestId": "req-error-1",
            },
        )

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as http_client:
        client = AqaraCloudClient(http_client=http_client)
        with pytest.raises(AqaraCloudAuthError) as exc_info:
            await client.list_devices(build_credentials())

    assert "accessToken invalid" in str(exc_info.value)


@pytest.mark.asyncio
async def test_request_uses_msg_details_when_message_missing() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "code": 5001,
                "msgDetails": "resource missing",
                "requestId": "req-error-2",
            },
        )

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as http_client:
        client = AqaraCloudClient(http_client=http_client)
        with pytest.raises(AqaraCloudRequestError) as exc_info:
            await client.list_devices(build_credentials())

    assert "resource missing" in str(exc_info.value)


@pytest.mark.asyncio
async def test_request_rejects_non_object_response_payload() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=["not-an-object"])

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as http_client:
        client = AqaraCloudClient(http_client=http_client)
        with pytest.raises(AqaraCloudRequestError):
            await client.list_devices(build_credentials())


@pytest.mark.asyncio
async def test_request_retries_rate_limit_then_succeeds() -> None:
    attempts = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            return httpx.Response(429, text="slow down")
        return httpx.Response(
            200,
            json={
                "code": 0,
                "message": "Success",
                "result": {"totalCount": 0, "data": []},
            },
        )

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as http_client:
        client = AqaraCloudClient(http_client=http_client, retry_attempts=2, retry_delay_seconds=0)
        devices = await client.list_devices(build_credentials())

    assert attempts == 2
    assert devices == []


@pytest.mark.asyncio
async def test_request_raises_rate_limit_after_final_429() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, text="slow down")

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as http_client:
        client = AqaraCloudClient(http_client=http_client, retry_attempts=2, retry_delay_seconds=0)
        with pytest.raises(AqaraCloudRateLimitError):
            await client.list_devices(build_credentials())


@pytest.mark.asyncio
async def test_request_retries_server_error_then_succeeds() -> None:
    attempts = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            return httpx.Response(500, text="server error")
        return httpx.Response(
            200,
            json={
                "code": 0,
                "message": "Success",
                "result": {"totalCount": 1, "data": [{"did": "lumi.1", "model": "lumi.sensor", "deviceName": "One"}]},
            },
        )

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as http_client:
        client = AqaraCloudClient(http_client=http_client, retry_attempts=2, retry_delay_seconds=0)
        devices = await client.list_devices(build_credentials())

    assert attempts == 2
    assert devices[0].did == "lumi.1"


@pytest.mark.asyncio
async def test_request_raises_request_error_after_final_5xx() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="server error")

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as http_client:
        client = AqaraCloudClient(http_client=http_client, retry_attempts=2, retry_delay_seconds=0)
        with pytest.raises(AqaraCloudRequestError) as exc_info:
            await client.list_devices(build_credentials())

    assert "query.device.info" in str(exc_info.value)


@pytest.mark.asyncio
async def test_request_retries_request_exception_then_succeeds() -> None:
    attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise httpx.ConnectError("network down", request=request)
        return httpx.Response(
            200,
            json={
                "code": 0,
                "message": "Success",
                "result": {"totalCount": 0, "data": []},
            },
        )

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as http_client:
        client = AqaraCloudClient(http_client=http_client, retry_attempts=2, retry_delay_seconds=0)
        devices = await client.list_devices(build_credentials())

    assert attempts == 2
    assert devices == []


@pytest.mark.asyncio
async def test_request_raises_request_error_after_final_request_exception() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("network down", request=request)

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as http_client:
        client = AqaraCloudClient(http_client=http_client, retry_attempts=2, retry_delay_seconds=0)
        with pytest.raises(AqaraCloudRequestError) as exc_info:
            await client.list_devices(build_credentials())

    assert "ConnectError" in str(exc_info.value)


@pytest.mark.asyncio
async def test_exchange_token_rejects_unexpected_result_shape() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"code": 0, "message": "Success", "result": []})

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as http_client:
        client = AqaraCloudClient(http_client=http_client)
        with pytest.raises(AqaraCloudRequestError):
            await client.exchange_token(build_credentials(), account="test@example.com", auth_code="123456")
