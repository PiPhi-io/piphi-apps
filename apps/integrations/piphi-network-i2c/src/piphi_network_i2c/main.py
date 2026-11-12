from __future__ import annotations

import multiprocessing
import os

import uvicorn


def main() -> None:
    multiprocessing.freeze_support()
    port = int(os.getenv("PIPHI_I2C_PORT", "3674"))
    uvicorn.run("piphi_network_i2c.app:create_app", factory=True, host="0.0.0.0", port=port)


if __name__ == "__main__":
    main()
