from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import httpx

STEAM_API_BASE_URL = "https://api.steampowered.com"
PERSONA_STATES = {
    0: "offline",
    1: "online",
    2: "busy",
    3: "away",
    4: "snooze",
    5: "looking_to_trade",
    6: "looking_to_play",
}


class SteamAPIError(RuntimeError):
    pass


class SteamAuthenticationError(SteamAPIError):
    pass


class SteamRateLimitError(SteamAPIError):
    pass


class SteamResponseError(SteamAPIError):
    pass


@dataclass(frozen=True, slots=True)
class SteamCredentials:
    steam_id: str
    web_api_key: str


@dataclass(frozen=True, slots=True)
class SteamSnapshot:
    sampled_at: str
    state: dict[str, Any]

    @property
    def metrics(self) -> dict[str, bool | int | float]:
        values = self.state
        return {
            "connected": True,
            "is_online": bool(values["is_online"]),
            "is_in_game": bool(values["is_in_game"]),
            "persona_state_code": int(values["persona_state_code"]),
            "owned_game_count": int(values["owned_game_count"]),
            "recent_game_count": int(values["recent_game_count"]),
            "total_playtime_minutes": int(values["total_playtime_minutes"]),
            "recent_playtime_minutes": int(values["recent_playtime_minutes"]),
        }


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return max(int(value), 0)
    except (TypeError, ValueError):
        return default


def _bounded_text(value: Any, limit: int = 160) -> str | None:
    if value is None:
        return None
    cleaned = "".join(character for character in str(value) if character.isprintable()).strip()
    return cleaned[:limit] or None


def normalize_snapshot(
    *,
    steam_id: str,
    player: dict[str, Any],
    recent_payload: dict[str, Any] | None,
    owned_payload: dict[str, Any] | None,
    sampled_at: str | None = None,
) -> SteamSnapshot:
    persona_code = _safe_int(player.get("personastate"))
    current_app_id = _bounded_text(player.get("gameid"), 20)
    current_game = _bounded_text(player.get("gameextrainfo"), 160)
    recent_games_raw = (recent_payload or {}).get("games")
    recent_games = []
    if isinstance(recent_games_raw, list):
        for item in recent_games_raw[:10]:
            if not isinstance(item, dict):
                continue
            recent_games.append(
                {
                    "app_id": _safe_int(item.get("appid")),
                    "name": _bounded_text(item.get("name"), 160) or "Unknown game",
                    "playtime_2weeks_minutes": _safe_int(item.get("playtime_2weeks")),
                    "playtime_forever_minutes": _safe_int(item.get("playtime_forever")),
                }
            )
    owned_games_raw = (owned_payload or {}).get("games")
    total_playtime = 0
    if isinstance(owned_games_raw, list):
        total_playtime = sum(
            _safe_int(game.get("playtime_forever"))
            for game in owned_games_raw
            if isinstance(game, dict)
        )
    recent_playtime = sum(game["playtime_2weeks_minutes"] for game in recent_games)
    last_logoff = _safe_int(player.get("lastlogoff"))
    state = {
        "steam_id": steam_id,
        "persona_name": _bounded_text(player.get("personaname"), 80) or f"Steam {steam_id}",
        "profile_url": _bounded_text(player.get("profileurl"), 300),
        "avatar_url": _bounded_text(player.get("avatarfull"), 500),
        "community_visibility_state": _safe_int(player.get("communityvisibilitystate")),
        "persona_state": PERSONA_STATES.get(persona_code, "unknown"),
        "persona_state_code": persona_code,
        "is_online": persona_code != 0,
        "is_in_game": bool(current_app_id or current_game),
        "current_game_app_id": current_app_id,
        "current_game_name": current_game,
        "last_logoff": last_logoff or None,
        "library_visible": owned_payload is not None,
        "recent_games_visible": recent_payload is not None,
        "owned_game_count": _safe_int((owned_payload or {}).get("game_count")),
        "recent_game_count": _safe_int(
            (recent_payload or {}).get("total_count"), len(recent_games)
        ),
        "total_playtime_minutes": total_playtime,
        "recent_playtime_minutes": recent_playtime,
        "recent_games": recent_games,
    }
    return SteamSnapshot(
        sampled_at=sampled_at or datetime.now(tz=UTC).isoformat(),
        state=state,
    )


class SteamWebAPIClient:
    def __init__(
        self,
        *,
        timeout_seconds: float = 15.0,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self.timeout_seconds = timeout_seconds
        self._http_client = http_client
        self._owns_client = http_client is None

    async def aclose(self) -> None:
        if self._http_client is not None and self._owns_client:
            await self._http_client.aclose()
        self._http_client = None

    async def _client(self) -> httpx.AsyncClient:
        if self._http_client is None:
            self._http_client = httpx.AsyncClient(timeout=self.timeout_seconds)
            self._owns_client = True
        return self._http_client

    async def _get(self, path: str, credentials: SteamCredentials, **params: Any) -> dict[str, Any]:
        client = await self._client()
        try:
            response = await client.get(
                f"{STEAM_API_BASE_URL}{path}",
                params=params,
                headers={"x-webapi-key": credentials.web_api_key, "accept": "application/json"},
            )
        except httpx.RequestError as exc:
            raise SteamResponseError(f"Steam Web API request failed: {type(exc).__name__}") from exc
        if response.status_code in {401, 403}:
            raise SteamAuthenticationError("Steam rejected the Web API key or account access.")
        if response.status_code == 429:
            raise SteamRateLimitError("Steam Web API rate limit exceeded.")
        if response.status_code >= 400:
            raise SteamResponseError(f"Steam Web API returned HTTP {response.status_code}.")
        try:
            payload = response.json()
        except ValueError as exc:
            raise SteamResponseError("Steam Web API returned invalid JSON.") from exc
        if not isinstance(payload, dict):
            raise SteamResponseError("Steam Web API returned an unexpected payload.")
        return payload

    async def fetch_snapshot(self, credentials: SteamCredentials) -> SteamSnapshot:
        summary_request = self._get(
            "/ISteamUser/GetPlayerSummaries/v2/",
            credentials,
            steamids=credentials.steam_id,
        )
        recent_request = self._get(
            "/IPlayerService/GetRecentlyPlayedGames/v1/",
            credentials,
            steamid=credentials.steam_id,
            count=10,
        )
        owned_request = self._get(
            "/IPlayerService/GetOwnedGames/v1/",
            credentials,
            steamid=credentials.steam_id,
            include_appinfo=False,
            include_played_free_games=True,
        )
        summary_result, recent_result, owned_result = await asyncio.gather(
            summary_request,
            recent_request,
            owned_request,
            return_exceptions=True,
        )
        if isinstance(summary_result, Exception):
            raise summary_result
        for optional_result in (recent_result, owned_result):
            if isinstance(
                optional_result,
                (SteamAuthenticationError, SteamRateLimitError),
            ):
                raise optional_result
        players = summary_result.get("response", {}).get("players", [])
        if not isinstance(players, list) or not players or not isinstance(players[0], dict):
            raise SteamResponseError("Steam returned no player for the configured SteamID64.")
        recent = None if isinstance(recent_result, Exception) else recent_result.get("response")
        owned = None if isinstance(owned_result, Exception) else owned_result.get("response")
        return normalize_snapshot(
            steam_id=credentials.steam_id,
            player=players[0],
            recent_payload=recent if isinstance(recent, dict) and "games" in recent else None,
            owned_payload=owned if isinstance(owned, dict) and "games" in owned else None,
        )
