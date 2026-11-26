from __future__ import annotations

import asyncio
import base64
import hashlib
import ipaddress
import logging
import os
import random
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from email.utils import parsedate_to_datetime
from typing import Any
from urllib.parse import urlparse

import httpx

from .models import AirthingsCloudDevice, AirthingsLatestSample


logger = logging.getLogger(__name__)

DEFAULT_ACCOUNTS_BASE_URL = "https://accounts-api.airthings.com"
DEFAULT_CONSUMER_BASE_URL = "https://consumer-api.airthings.com"
DEFAULT_HTTP_TIMEOUT_SECONDS = 15.0
DEFAULT_RETRY_ATTEMPTS = 3
DEFAULT_RETRY_DELAY_SECONDS = 1.0
MAX_RETRY_DELAY_SECONDS = 60.0
TOKEN_EXPIRY_SAFETY_SECONDS = 120
MAX_DEVICE_RECORDS = 500
MAX_ACCOUNT_RECORDS = 100
MAX_SENSOR_PAGES = 20
MAX_SENSOR_RECORDS = 1000
ACCOUNTS_BASE_URL_ENV = "PIPHI_AIRTHINGS_ACCOUNTS_BASE_URL"
CONSUMER_BASE_URL_ENV = "PIPHI_AIRTHINGS_CONSUMER_BASE_URL"
ALLOW_INSECURE_TEST_ENDPOINTS_ENV = "PIPHI_AIRTHINGS_ALLOW_INSECURE_TEST_ENDPOINTS"


def _jittered_delay(delay: float) -> float:
    return min(MAX_RETRY_DELAY_SECONDS, max(delay, 0.0) * random.uniform(1.0, 1.1))


def _safe_endpoint(url: str) -> str:
    return urlparse(url).path.rstrip("/").rsplit("/", 1)[-1] or "root"


class AirthingsCloudError(RuntimeError):
    """Base error for Airthings consumer cloud operations."""


class AirthingsCloudAuthError(AirthingsCloudError):
    """Raised when Airthings consumer cloud credentials are rejected."""


class AirthingsCloudRateLimitError(AirthingsCloudError):
    """Raised when Airthings consumer cloud rate limits the client."""

    def __init__(
        self,
        message: str,
        *,
        retry_after_seconds: float | None = None,
        quota_remaining: int | None = None,
    ) -> None:
        super().__init__(message)
        self.retry_after_seconds = retry_after_seconds
        self.quota_remaining = quota_remaining


class AirthingsCloudRequestError(AirthingsCloudError):
    """Raised for unexpected Airthings consumer cloud request failures."""


class AirthingsCloudContractError(AirthingsCloudRequestError):
    """Raised when a successful provider response violates its documented contract."""


class AirthingsCloudDeviceRemovedError(AirthingsCloudRequestError):
    """Raised when the selected device no longer appears in the selected account."""


def _retry_after_seconds(value: str | None) -> float | None:
    if not value:
        return None
    try:
        return max(float(value), 0.0)
    except ValueError:
        try:
            parsed = parsedate_to_datetime(value)
        except (TypeError, ValueError, OverflowError):
            return None
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=UTC)
        return max((parsed.astimezone(UTC) - datetime.now(tz=UTC)).total_seconds(), 0.0)


def _quota_remaining(response: httpx.Response) -> int | None:
    value = response.headers.get("X-RateLimit-Remaining")
    if value is None:
        return None
    try:
        return max(int(value), 0)
    except ValueError:
        return None


def _environment_base_url(name: str, default: str, *, allow_insecure: bool) -> str:
    value = str(os.getenv(name) or default).strip().rstrip("/")
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError(f"{name} must be an absolute HTTP(S) URL.")
    if value == default:
        return value
    try:
        is_loopback = parsed.hostname == "localhost" or ipaddress.ip_address(
            str(parsed.hostname or "")
        ).is_loopback
    except ValueError:
        is_loopback = False
    if not allow_insecure or not is_loopback:
        raise ValueError(
            f"{name} is fixed to the official Airthings endpoint unless "
            f"{ALLOW_INSECURE_TEST_ENDPOINTS_ENV}=true selects an isolated loopback fixture."
        )
    return value


def airthings_cloud_client_from_environment() -> AirthingsCloudClient:
    """Build the runtime client, permitting HTTP overrides only for explicit test fixtures."""
    allow_insecure = str(os.getenv(ALLOW_INSECURE_TEST_ENDPOINTS_ENV) or "").strip().lower() in {
        "1",
        "true",
        "yes",
    }
    return AirthingsCloudClient(
        accounts_base_url=_environment_base_url(
            ACCOUNTS_BASE_URL_ENV,
            DEFAULT_ACCOUNTS_BASE_URL,
            allow_insecure=allow_insecure,
        ),
        consumer_base_url=_environment_base_url(
            CONSUMER_BASE_URL_ENV,
            DEFAULT_CONSUMER_BASE_URL,
            allow_insecure=allow_insecure,
        ),
    )


@dataclass(slots=True, repr=False)
class AirthingsCredentials:
    client_id: str
    client_secret: str = field(repr=False)

    def cache_key(self) -> str:
        material = f"{self.client_id}\0{self.client_secret}".encode("utf-8")
        return hashlib.sha256(material).hexdigest()


@dataclass(slots=True, repr=False)
class _TokenRecord:
    access_token: str = field(repr=False)
    expires_at: datetime

    def is_expired(self) -> bool:
        return datetime.now(tz=UTC) >= self.expires_at


class AirthingsCloudClient:
    def __init__(
        self,
        *,
        accounts_base_url: str = DEFAULT_ACCOUNTS_BASE_URL,
        consumer_base_url: str = DEFAULT_CONSUMER_BASE_URL,
        timeout_seconds: float = DEFAULT_HTTP_TIMEOUT_SECONDS,
        retry_attempts: int = DEFAULT_RETRY_ATTEMPTS,
        retry_delay_seconds: float = DEFAULT_RETRY_DELAY_SECONDS,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self.accounts_base_url = accounts_base_url.rstrip("/")
        self.consumer_base_url = consumer_base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds
        self.retry_attempts = max(int(retry_attempts), 1)
        self.retry_delay_seconds = max(float(retry_delay_seconds), 0.0)
        self._http_client = http_client
        self._owns_http_client = http_client is None
        self._token_cache: dict[str, _TokenRecord] = {}
        self._validated_accounts: set[tuple[str, str]] = set()

    async def aclose(self) -> None:
        if self._http_client is not None and self._owns_http_client:
            await self._http_client.aclose()
        self._http_client = None

    async def _client(self) -> httpx.AsyncClient:
        if self._http_client is None:
            self._http_client = httpx.AsyncClient(timeout=self.timeout_seconds)
            self._owns_http_client = True
        return self._http_client

    async def _request(
        self,
        method: str,
        url: str,
        *,
        headers: dict[str, str] | None = None,
        json: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
    ) -> httpx.Response:
        client = await self._client()
        last_error: Exception | None = None
        for attempt in range(1, self.retry_attempts + 1):
            try:
                response = await client.request(
                    method,
                    url,
                    headers=headers,
                    json=json,
                    params=params,
                )
                if response.status_code == 429:
                    retry_after = _retry_after_seconds(
                        response.headers.get("X-RateLimit-Retry-After")
                        or response.headers.get("Retry-After")
                    )
                    quota_remaining = _quota_remaining(response)
                    if (
                        attempt >= self.retry_attempts
                        or (retry_after is not None and retry_after > MAX_RETRY_DELAY_SECONDS)
                    ):
                        raise AirthingsCloudRateLimitError(
                            "Airthings API rate limit exceeded.",
                            retry_after_seconds=retry_after,
                            quota_remaining=quota_remaining,
                        )
                    delay = (
                        retry_after
                        if retry_after is not None
                        else self.retry_delay_seconds * attempt
                    )
                    delay = _jittered_delay(delay)
                    logger.warning(
                        "Airthings API rate limit on %s %s attempt=%s/%s retry_in_seconds=%.2f",
                        method,
                        _safe_endpoint(url),
                        attempt,
                        self.retry_attempts,
                        delay,
                    )
                    await asyncio.sleep(delay)
                    continue
                if response.status_code >= 500:
                    if attempt >= self.retry_attempts:
                        return response
                    delay = _jittered_delay(self.retry_delay_seconds * attempt)
                    logger.warning(
                        "Airthings API server error on %s %s status=%s attempt=%s/%s retry_in_seconds=%.2f",
                        method,
                        _safe_endpoint(url),
                        response.status_code,
                        attempt,
                        self.retry_attempts,
                        delay,
                    )
                    await asyncio.sleep(delay)
                    continue
                return response
            except httpx.RequestError as exc:
                last_error = exc
                if attempt >= self.retry_attempts:
                    break
                delay = _jittered_delay(self.retry_delay_seconds * attempt)
                logger.warning(
                    "Airthings API request error on %s %s attempt=%s/%s retry_in_seconds=%.2f error=%r",
                    method,
                    _safe_endpoint(url),
                    attempt,
                    self.retry_attempts,
                    delay,
                    type(exc).__name__,
                )
                await asyncio.sleep(delay)

        if last_error is not None:
            raise AirthingsCloudRequestError(
                "Airthings API request failed due to a network error."
            ) from last_error
        raise AirthingsCloudRequestError("Airthings API request failed.")

    async def _access_token(self, credentials: AirthingsCredentials) -> str:
        cached = self._token_cache.get(credentials.cache_key())
        if cached is not None and not cached.is_expired():
            logger.debug(
                "Airthings token cache hit expires_at=%s",
                cached.expires_at.isoformat(),
            )
            return cached.access_token

        basic_token = base64.b64encode(
            f"{credentials.client_id}:{credentials.client_secret}".encode("utf-8")
        ).decode("ascii")
        response = await self._request(
            "POST",
            f"{self.accounts_base_url}/v1/token",
            headers={
                "Authorization": f"Basic {basic_token}",
                "Content-Type": "application/json",
            },
            json={
                "grant_type": "client_credentials",
                "client_id": credentials.client_id,
                "client_secret": credentials.client_secret,
                "scope": ["read:device:current_values"],
            },
        )
        if response.status_code in {400, 401, 403}:
            raise AirthingsCloudAuthError("Airthings consumer cloud credentials were rejected.")
        if response.status_code >= 400:
            raise AirthingsCloudRequestError(
                f"Airthings token request failed with status {response.status_code}."
            )
        try:
            payload = response.json()
        except ValueError as exc:
            raise AirthingsCloudContractError(
                "Airthings token response returned invalid JSON."
            ) from exc
        if not isinstance(payload, dict):
            raise AirthingsCloudContractError(
                "Airthings token response returned an unexpected payload."
            )
        access_token = str(payload.get("access_token") or "")
        try:
            expires_in = int(payload.get("expires_in") or 3600)
        except (TypeError, ValueError) as exc:
            raise AirthingsCloudContractError(
                "Airthings token response contained an invalid expiry."
            ) from exc
        if not access_token:
            raise AirthingsCloudContractError("Airthings token response did not include an access_token.")
        expires_at = datetime.now(tz=UTC) + timedelta(
            seconds=max(expires_in - TOKEN_EXPIRY_SAFETY_SECONDS, 60)
        )
        self._token_cache[credentials.cache_key()] = _TokenRecord(
            access_token=access_token,
            expires_at=expires_at,
        )
        logger.info(
            "Airthings token refreshed expires_at=%s",
            expires_at.isoformat(),
        )
        return access_token

    def _clear_cached_auth(self, credentials: AirthingsCredentials) -> None:
        key = credentials.cache_key()
        self._token_cache.pop(key, None)
        self._validated_accounts = {
            item for item in self._validated_accounts if item[0] != key
        }
        logger.warning("Airthings auth cache cleared")

    def forget_credentials(self, credentials: AirthingsCredentials) -> None:
        """Remove token/account cache material when credentials rotate or are deleted."""
        self._clear_cached_auth(credentials)

    async def list_account_ids(self, credentials: AirthingsCredentials) -> list[str]:
        access_token = await self._access_token(credentials)
        response = await self._request(
            "GET",
            f"{self.consumer_base_url}/v1/accounts",
            headers={"Authorization": f"Bearer {access_token}"},
        )
        if response.status_code in {401, 403}:
            self._clear_cached_auth(credentials)
            raise AirthingsCloudAuthError(
                "Airthings consumer cloud token was rejected while listing accounts."
            )
        if response.status_code >= 400:
            raise AirthingsCloudRequestError(
                f"Airthings account lookup failed with status {response.status_code}."
            )

        try:
            payload = response.json()
        except ValueError as exc:
            raise AirthingsCloudContractError(
                "Airthings account lookup returned invalid JSON."
            ) from exc
        raw_accounts = (
            payload.get("accounts")
            if isinstance(payload, dict) and isinstance(payload.get("accounts"), list)
            else payload
        )
        if not isinstance(raw_accounts, list):
            raise AirthingsCloudContractError("Airthings account lookup returned an unexpected payload.")
        if len(raw_accounts) > MAX_ACCOUNT_RECORDS:
            raise AirthingsCloudContractError(
                "Airthings account lookup exceeded the bounded record limit."
            )

        account_ids: list[str] = []
        for item in raw_accounts:
            if not isinstance(item, dict):
                continue
            account_id = str(item.get("id") or item.get("accountId") or "").strip()
            if account_id:
                if account_id in account_ids:
                    raise AirthingsCloudContractError(
                        "Airthings account lookup returned duplicate account records."
                    )
                account_ids.append(account_id)
        if not account_ids:
            raise AirthingsCloudContractError("Airthings account lookup returned no account ids.")
        return account_ids

    async def _validate_account_id(self, credentials: AirthingsCredentials, account_id: str) -> str:
        selected = str(account_id).strip()
        if not selected:
            raise AirthingsCloudRequestError("An explicit Airthings account id is required.")
        cache_key = (credentials.cache_key(), selected)
        if cache_key in self._validated_accounts:
            return selected
        if selected not in await self.list_account_ids(credentials):
            raise AirthingsCloudAuthError("The selected Airthings account is not accessible with these credentials.")
        self._validated_accounts.add(cache_key)
        return selected

    async def list_devices(
        self, credentials: AirthingsCredentials, *, account_id: str
    ) -> list[AirthingsCloudDevice]:
        access_token = await self._access_token(credentials)
        account_id = await self._validate_account_id(credentials, account_id)
        response = await self._request(
            "GET",
            f"{self.consumer_base_url}/v1/accounts/{account_id}/devices",
            headers={"Authorization": f"Bearer {access_token}"},
        )
        if response.status_code in {401, 403}:
            self._clear_cached_auth(credentials)
            raise AirthingsCloudAuthError("Airthings consumer cloud token was rejected while listing devices.")
        if response.status_code >= 400:
            raise AirthingsCloudRequestError(
                f"Airthings device discovery failed with status {response.status_code}."
            )
        try:
            payload = response.json()
        except ValueError as exc:
            raise AirthingsCloudContractError(
                "Airthings device discovery returned invalid JSON."
            ) from exc
        raw_devices = (
            payload.get("devices")
            if isinstance(payload, dict) and isinstance(payload.get("devices"), list)
            else payload
        )
        if not isinstance(raw_devices, list):
            raise AirthingsCloudContractError(
                "Airthings device discovery returned an unexpected payload."
            )
        if len(raw_devices) > MAX_DEVICE_RECORDS:
            raise AirthingsCloudContractError(
                "Airthings device discovery exceeded the bounded record limit."
            )
        devices: list[AirthingsCloudDevice] = []
        seen_serial_numbers: set[str] = set()
        for item in raw_devices:
            if not isinstance(item, dict):
                continue
            serial_number = str(item.get("serialNumber") or item.get("serial_number") or "").strip()
            if not serial_number:
                continue
            if serial_number in seen_serial_numbers:
                raise AirthingsCloudContractError(
                    "Airthings device discovery returned duplicate device records."
                )
            seen_serial_numbers.add(serial_number)
            devices.append(
                AirthingsCloudDevice(
                    serial_number=serial_number,
                    name=str(item.get("name") or item.get("deviceName") or serial_number),
                    device_type=item.get("type"),
                    sensors=list(item.get("sensors") or []),
                    home=item.get("home"),
                    segment_name=item.get("segmentName"),
                )
            )
        logger.info(
            "Airthings devices listed discovered=%s",
            len(devices),
        )
        return devices

    async def latest_sample(
        self,
        *,
        credentials: AirthingsCredentials,
        account_id: str,
        serial_number: str,
    ) -> AirthingsLatestSample:
        access_token = await self._access_token(credentials)
        account_id = await self._validate_account_id(credentials, account_id)
        matching_results: list[dict[str, Any]] = []
        page_number = 1
        total_record_count = 0
        while True:
            response = await self._request(
                "GET",
                f"{self.consumer_base_url}/v1/accounts/{account_id}/sensors",
                headers={"Authorization": f"Bearer {access_token}"},
                params={"sn": serial_number, "pageNumber": page_number},
            )
            if response.status_code in {401, 403}:
                self._clear_cached_auth(credentials)
                raise AirthingsCloudAuthError(
                    "Airthings consumer cloud token was rejected while reading a device."
                )
            if response.status_code >= 400:
                raise AirthingsCloudRequestError(
                    f"Airthings latest sample failed with status {response.status_code}."
                )
            try:
                payload = response.json()
            except ValueError as exc:
                raise AirthingsCloudContractError(
                    "Airthings latest sample returned invalid JSON."
                ) from exc
            raw_results = (
                payload.get("results")
                if isinstance(payload, dict) and isinstance(payload.get("results"), list)
                else payload
            )
            if not isinstance(raw_results, list):
                raise AirthingsCloudContractError(
                    "Airthings latest sample returned an unexpected payload."
                )
            total_record_count += len(raw_results)
            if total_record_count > MAX_SENSOR_RECORDS:
                raise AirthingsCloudContractError(
                    "Airthings sensor response exceeded the bounded record limit."
                )
            for item in raw_results:
                if not isinstance(item, dict):
                    continue
                item_serial = str(
                    item.get("serialNumber") or item.get("serial_number") or ""
                ).strip()
                if item_serial == serial_number:
                    matching_results.append(item)

            has_next = bool(payload.get("hasNext")) if isinstance(payload, dict) else False
            total_pages = payload.get("totalPages") if isinstance(payload, dict) else None
            if total_pages is not None:
                try:
                    parsed_total_pages = int(total_pages)
                except (TypeError, ValueError) as exc:
                    raise AirthingsCloudContractError(
                        "Airthings sensor pagination metadata was invalid."
                    ) from exc
                if parsed_total_pages < 1 or parsed_total_pages > MAX_SENSOR_PAGES:
                    raise AirthingsCloudContractError(
                        "Airthings sensor pagination exceeded the bounded page limit."
                    )
                has_next = has_next or page_number < parsed_total_pages
            if not has_next:
                break
            if page_number >= MAX_SENSOR_PAGES:
                raise AirthingsCloudContractError(
                    "Airthings sensor pagination exceeded the bounded page limit."
                )
            page_number += 1

        if len(matching_results) > 1:
            raise AirthingsCloudContractError(
                "Airthings latest sample returned duplicate device records."
            )
        if matching_results:
            try:
                sample = AirthingsLatestSample.from_api_payload(
                    serial_number, matching_results[0]
                )
            except ValueError as exc:
                raise AirthingsCloudContractError(
                    "Airthings latest sample contained an invalid timestamp."
                ) from exc
            logger.info("Airthings sample fetched pages=%s", page_number)
            return sample

        raise AirthingsCloudDeviceRemovedError(
            "The selected Airthings device was not found in the selected cloud account."
        )
