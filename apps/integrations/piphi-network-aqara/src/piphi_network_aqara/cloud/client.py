from __future__ import annotations

import asyncio
import hashlib
import logging
import secrets
import time
from typing import Any

import httpx

from .models import AqaraAuthTokens, AqaraCloudCredentials, AqaraCloudDevice, AqaraResourceInfo, AqaraResourceValue


logger = logging.getLogger(__name__)

DEFAULT_API_DOMAINS = {
    "cn": "open-cn.aqara.com",
    "us": "open-usa.aqara.com",
    "eu": "open-ger.aqara.com",
    "kr": "open-kr.aqara.com",
    "ru": "open-ru.aqara.com",
    "sg": "open-sg.aqara.com",
}
DEFAULT_HTTP_TIMEOUT_SECONDS = 20.0
DEFAULT_RETRY_ATTEMPTS = 3
DEFAULT_RETRY_DELAY_SECONDS = 1.0


class AqaraCloudError(RuntimeError):
    """Base error for Aqara cloud operations."""


class AqaraCloudAuthError(AqaraCloudError):
    """Raised when Aqara cloud credentials are rejected."""


class AqaraCloudRateLimitError(AqaraCloudError):
    """Raised when Aqara cloud rate limits the client."""


class AqaraCloudRequestError(AqaraCloudError):
    """Raised for unexpected Aqara cloud request failures."""


class AqaraCloudClient:
    def __init__(
        self,
        *,
        timeout_seconds: float = DEFAULT_HTTP_TIMEOUT_SECONDS,
        retry_attempts: int = DEFAULT_RETRY_ATTEMPTS,
        retry_delay_seconds: float = DEFAULT_RETRY_DELAY_SECONDS,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self.timeout_seconds = timeout_seconds
        self.retry_attempts = max(int(retry_attempts), 1)
        self.retry_delay_seconds = max(float(retry_delay_seconds), 0.0)
        self._http_client = http_client
        self._owns_http_client = http_client is None
        self._resource_cache: dict[str, list[AqaraResourceInfo]] = {}

    async def aclose(self) -> None:
        if self._http_client is not None and self._owns_http_client:
            await self._http_client.aclose()
        self._http_client = None

    async def _client(self) -> httpx.AsyncClient:
        if self._http_client is None:
            self._http_client = httpx.AsyncClient(timeout=self.timeout_seconds)
            self._owns_http_client = True
        return self._http_client

    def _base_url(self, credentials: AqaraCloudCredentials) -> str:
        domain = str(credentials.custom_api_domain or "").strip() or DEFAULT_API_DOMAINS.get(
            str(credentials.region or "").strip().lower(),
            "",
        )
        if not domain:
            raise AqaraCloudRequestError(
                f"Unsupported Aqara region '{credentials.region}'. Provide custom_api_domain or use one of: {', '.join(sorted(DEFAULT_API_DOMAINS))}."
            )
        if domain.startswith("http://") or domain.startswith("https://"):
            return domain.rstrip("/")
        return f"https://{domain.rstrip('/')}"

    def _signed_headers(
        self,
        credentials: AqaraCloudCredentials,
        *,
        access_token: str | None,
    ) -> dict[str, str]:
        nonce = secrets.token_hex(8)
        request_time = str(int(time.time() * 1000))
        parts: list[tuple[str, str]] = []
        if access_token:
            parts.append(("Accesstoken", access_token))
        parts.extend(
            [
                ("Appid", credentials.app_id),
                ("Keyid", credentials.key_id),
                ("Nonce", nonce),
                ("Time", request_time),
            ]
        )
        sign_payload = "&".join(f"{key}={value}" for key, value in parts) + credentials.app_key
        sign = hashlib.md5(sign_payload.lower().encode("utf-8")).hexdigest()
        headers = {key: value for key, value in parts}
        headers["Sign"] = sign
        headers["Lang"] = credentials.lang or "en"
        headers["Content-Type"] = "application/json"
        return headers

    async def _request(
        self,
        credentials: AqaraCloudCredentials,
        *,
        payload: dict[str, Any],
        include_access_token: bool,
    ) -> dict[str, Any]:
        client = await self._client()
        url = f"{self._base_url(credentials)}/v3.0/open/api"
        headers = self._signed_headers(
            credentials,
            access_token=credentials.access_token if include_access_token else None,
        )
        last_error: Exception | None = None
        for attempt in range(1, self.retry_attempts + 1):
            try:
                response = await client.post(url, headers=headers, json=payload)
                if response.status_code == 429:
                    if attempt >= self.retry_attempts:
                        raise AqaraCloudRateLimitError("Aqara cloud API rate limit exceeded.")
                    delay = self.retry_delay_seconds * attempt
                    await asyncio.sleep(delay)
                    continue
                if response.status_code >= 500:
                    if attempt >= self.retry_attempts:
                        break
                    delay = self.retry_delay_seconds * attempt
                    await asyncio.sleep(delay)
                    continue
                if response.status_code in {401, 403}:
                    raise AqaraCloudAuthError(
                        f"Aqara cloud request was rejected with status {response.status_code}."
                    )
                if response.status_code >= 400:
                    raise AqaraCloudRequestError(
                        f"Aqara cloud request failed with status {response.status_code}: {response.text}"
                    )
                payload_json = response.json()
                if not isinstance(payload_json, dict):
                    raise AqaraCloudRequestError("Aqara cloud returned a non-object response payload.")
                code = int(payload_json.get("code") or 0)
                if code != 0:
                    message = str(payload_json.get("message") or payload_json.get("msgDetails") or "Aqara request failed")
                    lowered = message.lower()
                    if any(token in lowered for token in ("token", "auth", "permission", "unauthorized")):
                        raise AqaraCloudAuthError(message)
                    raise AqaraCloudRequestError(message)
                return payload_json
            except httpx.RequestError as exc:
                last_error = exc
                if attempt >= self.retry_attempts:
                    break
                delay = self.retry_delay_seconds * attempt
                await asyncio.sleep(delay)
        if last_error is not None:
            raise AqaraCloudRequestError(
                f"Aqara cloud request failed: {type(last_error).__name__}: {last_error}"
            ) from last_error
        raise AqaraCloudRequestError(f"Aqara cloud request failed for payload intent={payload.get('intent')!r}")

    async def _request_intent(
        self,
        credentials: AqaraCloudCredentials,
        *,
        intent: str,
        data: Any,
        include_access_token: bool = True,
    ) -> Any:
        payload_json = await self._request(
            credentials,
            payload={"intent": intent, "data": data},
            include_access_token=include_access_token,
        )
        return payload_json.get("result")

    async def exchange_token(
        self,
        credentials: AqaraCloudCredentials,
        *,
        account: str,
        auth_code: str,
        account_type: int = 0,
    ) -> AqaraAuthTokens:
        result = await self._request_intent(
            credentials,
            intent="config.auth.getToken",
            data={
                "authCode": auth_code,
                "account": account,
                "accountType": int(account_type),
            },
            include_access_token=False,
        )
        if not isinstance(result, dict):
            raise AqaraCloudRequestError("Aqara token exchange returned an unexpected payload.")
        return AqaraAuthTokens(
            access_token=str(result.get("accessToken") or "").strip(),
            refresh_token=str(result.get("refreshToken") or "").strip() or None,
            open_id=str(result.get("openId") or "").strip(),
            expires_in=_coerce_int(result.get("expiresIn")),
        )

    async def refresh_access_token(self, credentials: AqaraCloudCredentials) -> AqaraAuthTokens:
        refresh_token = str(credentials.refresh_token or "").strip()
        if not refresh_token:
            raise AqaraCloudAuthError("Aqara refresh_token is required to refresh an expired access token.")
        result = await self._request_intent(
            credentials,
            intent="config.auth.refreshToken",
            data={"refreshToken": refresh_token},
            include_access_token=False,
        )
        if not isinstance(result, dict):
            raise AqaraCloudRequestError("Aqara token refresh returned an unexpected payload.")
        return AqaraAuthTokens(
            access_token=str(result.get("accessToken") or "").strip(),
            refresh_token=str(result.get("refreshToken") or "").strip() or None,
            open_id=str(result.get("openId") or "").strip(),
            expires_in=_coerce_int(result.get("expiresIn")),
        )

    async def list_devices(
        self,
        credentials: AqaraCloudCredentials,
        *,
        position_id: str = "",
        page_size: int = 100,
    ) -> list[AqaraCloudDevice]:
        devices: list[AqaraCloudDevice] = []
        page_num = 1
        while True:
            result = await self._request_intent(
                credentials,
                intent="query.device.info",
                data={
                    "positionId": position_id,
                    "pageNum": page_num,
                    "pageSize": page_size,
                },
            )
            if not isinstance(result, dict):
                raise AqaraCloudRequestError("Aqara device discovery returned an unexpected payload.")
            raw_devices = result.get("data") if isinstance(result.get("data"), list) else []
            total_count = _coerce_int(result.get("totalCount"))
            for item in raw_devices:
                if not isinstance(item, dict):
                    continue
                did = str(item.get("did") or "").strip()
                if not did:
                    continue
                devices.append(
                    AqaraCloudDevice(
                        did=did,
                        name=str(item.get("deviceName") or did),
                        model=str(item.get("model") or "").strip(),
                        parent_did=str(item.get("parentDid") or "").strip() or None,
                        position_id=str(item.get("positionId") or "").strip() or None,
                        model_type=_coerce_int(item.get("modelType")),
                        state=_coerce_int(item.get("state")),
                        firmware_version=str(item.get("firmwareVersion") or "").strip() or None,
                        time_zone=str(item.get("timeZone") or "").strip() or None,
                        raw=dict(item),
                    )
                )
            if not raw_devices:
                break
            if total_count is not None:
                if len(devices) >= total_count:
                    break
            elif len(raw_devices) < page_size:
                break
            page_num += 1
        logger.info(
            "Aqara devices listed region=%s open_id=%s discovered=%s",
            credentials.region,
            credentials.open_id or "unknown",
            len(devices),
        )
        return devices

    async def resource_info(self, credentials: AqaraCloudCredentials, *, model: str) -> list[AqaraResourceInfo]:
        cache_key = f"{credentials.region}:{model}"
        cached = self._resource_cache.get(cache_key)
        if cached is not None:
            return cached
        result = await self._request_intent(
            credentials,
            intent="query.resource.info",
            data={"model": model},
        )
        if not isinstance(result, list):
            raise AqaraCloudRequestError("Aqara resource metadata returned an unexpected payload.")
        resources: list[AqaraResourceInfo] = []
        for item in result:
            if not isinstance(item, dict):
                continue
            resource_id = str(item.get("resourceId") or "").strip()
            if not resource_id:
                continue
            resources.append(
                AqaraResourceInfo(
                    resource_id=resource_id,
                    name=str(item.get("name") or resource_id).strip(),
                    description=str(item.get("description") or "").strip() or None,
                    access=_coerce_int(item.get("access")),
                    unit=_coerce_int(item.get("unit")),
                    enums=str(item.get("enums") or "").strip() or None,
                    default_value=str(item.get("defaultValue") or "").strip() or None,
                    min_value=_coerce_int(item.get("minValue")),
                    max_value=_coerce_int(item.get("maxValue")),
                    model=str(item.get("model") or model).strip(),
                    raw=dict(item),
                )
            )
        self._resource_cache[cache_key] = resources
        return resources

    async def resource_values(
        self,
        credentials: AqaraCloudCredentials,
        *,
        subject_id: str,
        resource_ids: list[str] | None = None,
    ) -> list[AqaraResourceValue]:
        resource_request: dict[str, Any] = {"subjectId": subject_id}
        if resource_ids:
            resource_request["resourceIds"] = resource_ids
        result = await self._request_intent(
            credentials,
            intent="query.resource.value",
            data={"resources": [resource_request]},
        )
        if not isinstance(result, list):
            raise AqaraCloudRequestError("Aqara resource value query returned an unexpected payload.")
        values: list[AqaraResourceValue] = []
        for item in result:
            if not isinstance(item, dict):
                continue
            if str(item.get("subjectId") or "").strip() != subject_id:
                continue
            resource_id = str(item.get("resourceId") or "").strip()
            if not resource_id:
                continue
            values.append(
                AqaraResourceValue(
                    subject_id=subject_id,
                    resource_id=resource_id,
                    value=str(item.get("value") or "").strip(),
                    timestamp_ms=_coerce_int(item.get("timeStamp")),
                )
            )
        return values

    async def write_resource(
        self,
        credentials: AqaraCloudCredentials,
        *,
        subject_id: str,
        resource_id: str,
        value: str,
    ) -> None:
        await self._request_intent(
            credentials,
            intent="write.resource.device",
            data=[
                {
                    "subjectId": subject_id,
                    "resources": [
                        {
                            "resourceId": resource_id,
                            "value": value,
                        }
                    ],
                }
            ],
        )

    async def subscribe_resources(
        self,
        credentials: AqaraCloudCredentials,
        *,
        resources: list[dict[str, Any]],
    ) -> None:
        await self._request_intent(
            credentials,
            intent="config.resource.subscribe",
            data={"resources": resources},
        )

    async def unsubscribe_resources(
        self,
        credentials: AqaraCloudCredentials,
        *,
        resources: list[dict[str, Any]],
    ) -> None:
        await self._request_intent(
            credentials,
            intent="config.resource.unsubscribe",
            data={"resources": resources},
        )


def _coerce_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None
