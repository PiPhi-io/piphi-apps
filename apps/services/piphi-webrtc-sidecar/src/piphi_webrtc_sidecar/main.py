from __future__ import annotations

from .app import create_app
from .settings import runtime_port

app = create_app()


def main() -> None:
    import uvicorn

    # Analysis-media references are bearer capabilities carried in request paths.
    # Uvicorn's default access log records the full path, so it must stay disabled.
    uvicorn.run(app, host="0.0.0.0", port=runtime_port(), access_log=False)


if __name__ == "__main__":
    main()
