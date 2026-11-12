from __future__ import annotations

import uvicorn


def main() -> None:
    uvicorn.run("piphi_network_steam.app:app", host="0.0.0.0", port=8090)


if __name__ == "__main__":
    main()
