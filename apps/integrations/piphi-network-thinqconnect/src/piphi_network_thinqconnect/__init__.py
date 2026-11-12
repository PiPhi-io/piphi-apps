import json
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

__all__ = ["__version__"]

try:
    __version__ = version("piphi-network-thinqconnect")
except PackageNotFoundError:
    manifest = json.loads((Path(__file__).resolve().parent.parent / "manifest.json").read_text())
    __version__ = str(manifest["version"])
