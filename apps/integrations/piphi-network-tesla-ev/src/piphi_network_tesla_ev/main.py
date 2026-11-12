from __future__ import annotations

import os

import uvicorn

from .app import app


def main() -> None:
    uvicorn.run(
        "piphi_network_tesla_ev.main:app",
        host="0.0.0.0",
        port=int(os.getenv("PORT", "3090")),
    )


if __name__ == "__main__":
    main()
