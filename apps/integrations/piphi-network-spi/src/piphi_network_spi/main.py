from __future__ import annotations

import multiprocessing
import os

import uvicorn


def main() -> None:
    multiprocessing.freeze_support()
    port = int(os.getenv("PIPHI_SPI_PORT", "3675"))
    uvicorn.run("piphi_network_spi.app:create_app", factory=True, host="0.0.0.0", port=port)


if __name__ == "__main__":
    main()
