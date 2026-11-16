from __future__ import annotations

import inspect
from contextlib import asynccontextmanager
from typing import Any

from piphi_network_thinqconnect.lib.normalization import normalize_discovered_device, stable_client_id
from piphi_network_thinqconnect.lib.refrigerator import derive_refrigerator_controls


class ThinQClientError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        category: str = "transient_outage",
        retryable: bool = True,
    ) -> None:
        super().__init__(message)
        self.category = category
        self.retryable = retryable


def classify_thinq_error(exc: Exception) -> ThinQClientError:
    """Classify SDK/HTTP failures without exposing vendor response bodies."""
    if isinstance(exc, ThinQClientError):
        return exc

    status: int | None = None
    for candidate in (exc, getattr(exc, "response", None)):
        if candidate is None:
            continue
        for attribute in ("status", "status_code", "code"):
            value = getattr(candidate, attribute, None)
            if isinstance(value, int):
                status = value
                break
        if status is not None:
            break

    text = str(exc).casefold()
    if ("region" in text or "country" in text) and any(
        term in text for term in ("invalid", "unsupported", "not available", "mismatch")
    ):
        return ThinQClientError(
            "ThinQ country or region is not eligible",
            category="invalid_region",
            retryable=False,
        )
    if status == 429 or any(term in text for term in ("rate limit", "too many requests", "quota")):
        return ThinQClientError(
            "ThinQ request rate limit reached",
            category="rate_limited",
            retryable=True,
        )
    if status == 401 or any(
        term in text for term in ("invalid token", "token expired", "expired token", "invalid pat")
    ):
        return ThinQClientError(
            "ThinQ personal access token is invalid or expired",
            category="invalid_pat",
            retryable=False,
        )
    if status == 403 or any(
        term in text for term in ("forbidden", "not authorized", "permission denied", "insufficient scope")
    ):
        return ThinQClientError(
            "ThinQ account authorization does not permit this request",
            category="authorization_required",
            retryable=False,
        )
    if status == 404 or any(term in text for term in ("device not found", "unsupported device")):
        return ThinQClientError(
            "ThinQ device is unavailable or unsupported",
            category="unsupported_device",
            retryable=False,
        )
    return ThinQClientError(
        "ThinQ cloud is temporarily unavailable",
        category="transient_outage",
        retryable=True,
    )


class ThinQApiClient:
    async def discover_devices(
        self,
        *,
        access_token: str,
        country_code: str,
        client_id: str | None = None,
    ) -> list[dict[str, Any]]:
        effective_client_id = client_id or stable_client_id(
            access_token=access_token,
            country_code=country_code,
        )
        async with self._api(access_token=access_token, country_code=country_code, client_id=effective_client_id) as api:
            raw_devices = await self._call_first_available(
                api,
                ["async_get_device_list", "get_device_list"],
            )
        if not isinstance(raw_devices, list):
            raise ThinQClientError("ThinQ device list response was invalid")
        return [normalize_discovered_device(device) for device in raw_devices if isinstance(device, dict)]

    async def fetch_device_snapshot(
        self,
        *,
        access_token: str,
        country_code: str,
        device_id: str,
        device_type: str,
        client_id: str | None = None,
    ) -> dict[str, Any]:
        effective_client_id = client_id or stable_client_id(
            access_token=access_token,
            country_code=country_code,
            device_id=device_id,
        )
        async with self._api(access_token=access_token, country_code=country_code, client_id=effective_client_id) as api:
            raw_devices = await self._call_first_available(api, ["async_get_device_list", "get_device_list"])
            raw_device = self._find_device(raw_devices, device_id=device_id)
            raw_status = await self._call_with_signatures(
                api,
                ["async_get_device_status", "get_device_status"],
                [(device_id,), tuple()],
                fallback_kwargs={"device_id": device_id},
                allow_missing=False,
            )
            raw_profile = await self._call_with_signatures(
                api,
                ["async_get_device_profile", "get_device_profile"],
                [(device_id,), (device_type, device_id), tuple()],
                fallback_kwargs={"device_type": device_type, "device_id": device_id},
                allow_missing=True,
            )
            raw_controls = await self._call_with_signatures(
                api,
                ["async_get_device_available_controls", "get_device_available_controls"],
                [(device_type, device_id), (device_id,), tuple()],
                fallback_kwargs={"device_type": device_type, "device_id": device_id},
                allow_missing=True,
            )
            if not raw_controls and str(device_type).strip().upper() == "DEVICE_REFRIGERATOR":
                raw_controls = derive_refrigerator_controls(
                    raw_profile if isinstance(raw_profile, dict) else {}
                )
        return {
            "device": raw_device,
            "status": raw_status if isinstance(raw_status, dict) else {},
            "profile": raw_profile if isinstance(raw_profile, dict) else {},
            "available_controls": raw_controls if isinstance(raw_controls, (dict, list)) else {},
            "client_id": effective_client_id,
        }

    async def execute_device_command(
        self,
        *,
        access_token: str,
        country_code: str,
        device_id: str,
        device_type: str,
        control_method: str,
        control_params: dict[str, Any],
        control_resource: str | None = None,
        client_id: str | None = None,
    ) -> dict[str, Any]:
        effective_client_id = client_id or stable_client_id(
            access_token=access_token,
            country_code=country_code,
            device_id=device_id,
        )
        async with self._api(access_token=access_token, country_code=country_code, client_id=effective_client_id) as api:
            if not control_resource:
                raise ThinQClientError(
                    f"ThinQ control '{control_method}' is missing its negotiated resource"
                )
            result = await self._call_with_signatures(
                api,
                ["async_post_device_control", "post_device_control"],
                [(device_id, {control_resource: control_params})],
                fallback_kwargs={
                    "device_id": device_id,
                    "payload": {control_resource: control_params},
                },
                allow_missing=False,
            )
        if isinstance(result, dict):
            return result
        return {
            "status": "ok",
            "control_method": control_method,
            "control_params": control_params,
            "result": result,
        }

    def _find_device(self, raw_devices: Any, *, device_id: str) -> dict[str, Any]:
        if isinstance(raw_devices, list):
            for raw_device in raw_devices:
                if not isinstance(raw_device, dict):
                    continue
                candidate_id = raw_device.get("deviceId") or raw_device.get("device_id") or raw_device.get("id")
                if str(candidate_id) == str(device_id):
                    return raw_device
        raise ThinQClientError(
            "ThinQ device is unavailable or unsupported",
            category="unsupported_device",
            retryable=False,
        )

    async def _call_with_signatures(
        self,
        api: Any,
        method_names: list[str],
        signatures: list[tuple[Any, ...]],
        *,
        fallback_kwargs: dict[str, Any] | None = None,
        allow_missing: bool,
    ) -> Any:
        errors: list[Exception] = []
        for method_name in method_names:
            method = getattr(api, method_name, None)
            if method is None:
                continue
            for signature in signatures:
                try:
                    return await self._resolve_call(method, *signature)
                except TypeError as exc:
                    errors.append(exc)
                    continue
                except Exception as exc:
                    classified = classify_thinq_error(exc)
                    if allow_missing and classified.category == "unsupported_device":
                        return {}
                    raise classified from exc
            if fallback_kwargs:
                try:
                    return await self._resolve_call(method, **fallback_kwargs)
                except TypeError as exc:
                    errors.append(exc)
                except Exception as exc:
                    classified = classify_thinq_error(exc)
                    if allow_missing and classified.category == "unsupported_device":
                        return {}
                    raise classified from exc
        if allow_missing:
            return {}
        if errors:
            raise classify_thinq_error(errors[-1])
        raise ThinQClientError(f"ThinQ SDK method not available: {method_names[0]}")

    async def _call_first_available(self, api: Any, method_names: list[str]) -> Any:
        for method_name in method_names:
            method = getattr(api, method_name, None)
            if method is None:
                continue
            try:
                return await self._resolve_call(method)
            except TypeError:
                continue
            except Exception as exc:
                raise classify_thinq_error(exc) from exc
        raise ThinQClientError(f"ThinQ SDK method not available: {method_names[0]}")

    async def _resolve_call(self, func: Any, *args: Any, **kwargs: Any) -> Any:
        value = func(*args, **kwargs)
        if inspect.isawaitable(value):
            return await value
        return value

    @asynccontextmanager
    async def _api(self, *, access_token: str, country_code: str, client_id: str):
        try:
            from aiohttp import ClientSession
            from thinqconnect.thinq_api import ThinQApi
        except ImportError as exc:
            raise ThinQClientError(
                "The 'thinqconnect' package is not installed. Install runtime dependencies before running this integration."
            ) from exc

        async with ClientSession() as session:
            api = ThinQApi(
                session=session,
                access_token=access_token,
                country_code=country_code,
                client_id=client_id,
            )
            yield api
