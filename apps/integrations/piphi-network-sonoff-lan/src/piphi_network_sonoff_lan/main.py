from __future__ import annotations

from .app import create_app
from .settings import runtime_port

app = create_app()


def main() -> None:
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=runtime_port())


if __name__ == "__main__":
    main()
