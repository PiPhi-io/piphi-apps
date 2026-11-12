from __future__ import annotations

from html import escape
from typing import Any

from .plex_client import PlexServer


SIMULATED_SERVER = PlexServer(
    machine_id="simulated-home",
    name="Simulated Plex Home",
    base_url="simulator://plex",
    token="simulator",
)

SIMULATED_ITEMS: list[dict[str, Any]] = [
    {
        "ratingKey": "movie-1",
        "type": "movie",
        "title": "The Last Signal",
        "year": 2025,
        "duration": 6840000,
        "viewOffset": 2460000,
        "summary": "A deep-space relay receives a message that should not exist.",
        "thumb": "/simulator/art/last-signal.svg",
    },
    {
        "ratingKey": "episode-1",
        "type": "episode",
        "title": "A Quiet Orbit",
        "grandparentTitle": "Northern Skies",
        "parentTitle": "Season 2",
        "year": 2026,
        "duration": 3120000,
        "viewOffset": 1050000,
        "summary": "The crew follows a fading beacon beyond the mapped route.",
        "thumb": "/simulator/art/quiet-orbit.svg",
    },
    {
        "ratingKey": "track-1",
        "type": "track",
        "title": "Night Drive",
        "grandparentTitle": "The Satellites",
        "parentTitle": "City Lights",
        "year": 2024,
        "duration": 248000,
        "summary": "A synth-pop favorite from the simulated music library.",
        "thumb": "/simulator/art/night-drive.svg",
    },
]


class SimulatedPlexClient:
    """Deterministic Plex API surface used by the real runtime in demo mode."""

    async def discover(self, *_args: Any, **_kwargs: Any) -> list[PlexServer]:
        return [SIMULATED_SERVER]

    async def request(
        self,
        _server: PlexServer,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        method: str = "GET",
    ) -> dict[str, Any]:
        del method
        params = params or {}
        if path == "/":
            return {"MediaContainer": {"machineIdentifier": SIMULATED_SERVER.machine_id, "friendlyName": SIMULATED_SERVER.name}}
        if path == "/status/sessions":
            return {"MediaContainer": {"Metadata": [{**SIMULATED_ITEMS[1], "sessionKey": "session-1", "User": {"title": "Demo User"}, "Player": {"title": "Living Room TV", "state": "playing"}}]}}
        if path == "/library/sections":
            return {"MediaContainer": {"Directory": [
                {"key": "1", "type": "movie", "title": "Movies", "leafCount": 24},
                {"key": "2", "type": "show", "title": "TV Shows", "leafCount": 18},
                {"key": "3", "type": "artist", "title": "Music", "leafCount": 42},
            ]}}
        if path.startswith("/library/metadata/"):
            item_id = path.rsplit("/", 1)[-1]
            item = next((item for item in SIMULATED_ITEMS if item["ratingKey"] == item_id), None)
            return {"MediaContainer": {"Metadata": [item] if item else []}}
        if path == "/hubs/search":
            query = str(params.get("query") or "").lower()
            items = [item for item in SIMULATED_ITEMS if query in " ".join((str(item.get("title") or ""), str(item.get("grandparentTitle") or ""))).lower()]
            return {"MediaContainer": {"Metadata": items}}
        if path.startswith("/library/sections/") and path.endswith("/all"):
            section = path.split("/")[3]
            kinds = {"1": {"movie"}, "2": {"episode"}, "3": {"track"}}.get(section, set())
            return {"MediaContainer": {"Metadata": [item for item in SIMULATED_ITEMS if item["type"] in kinds]}}
        if path in {"/library/recentlyAdded", "/library/onDeck", "/hubs/continueWatching"}:
            return {"MediaContainer": {"Metadata": SIMULATED_ITEMS}}
        return {"ok": True}

    async def bytes(self, _server: PlexServer, path: str) -> tuple[bytes, str]:
        title = escape(path.rsplit("/", 1)[-1].removesuffix(".svg").replace("-", " ").title())
        svg = f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 640 360"><defs><linearGradient id="g" x2="1" y2="1"><stop stop-color="#171717"/><stop offset="1" stop-color="#3d2c07"/></linearGradient></defs><rect width="640" height="360" rx="28" fill="url(#g)"/><path d="M282 105v150l120-75z" fill="#e5a00d"/><text x="32" y="326" fill="white" font-family="sans-serif" font-size="28">{title}</text></svg>'''
        return svg.encode("utf-8"), "image/svg+xml"

    @staticmethod
    def metadata(payload: dict[str, Any]) -> list[dict[str, Any]]:
        from .plex_client import PlexClient

        return PlexClient.metadata(payload)

    @staticmethod
    def media_container(payload: dict[str, Any]) -> dict[str, Any]:
        from .plex_client import PlexClient

        return PlexClient.media_container(payload)
