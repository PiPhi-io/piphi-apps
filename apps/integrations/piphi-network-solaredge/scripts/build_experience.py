#!/usr/bin/env python3
"""Build and sign the integration-owned SolarEdge experience package."""

from __future__ import annotations

import argparse
import base64
import hashlib
import io
import json
import os
import tempfile
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

ROOT = Path(__file__).resolve().parents[1]
EXPERIENCE_ROOT = ROOT / "experiences" / "solar-energy"
SOURCE = EXPERIENCE_ROOT / "package.source.json"
SIGNING_CONTEXT = b"piphi-widget-package-manifest-v1\0"


def _archive(source: dict) -> bytes:
    payload = json.dumps(source, ensure_ascii=False, indent=2).encode("utf-8") + b"\n"
    assets = sorted({
        theme["stylesheet"]
        for widget in source["widgets"]
        for theme in widget.get("themes", [])
    })
    output = io.BytesIO()
    with ZipFile(output, "w") as package:
        _write_archive_member(package, "package.source.json", payload)
        for asset in assets:
            path = EXPERIENCE_ROOT / asset
            if not path.is_file():
                raise SystemExit(f"experience asset is missing: {asset}")
            _write_archive_member(package, asset, path.read_bytes())
    return output.getvalue()


def _write_archive_member(package: ZipFile, name: str, payload: bytes) -> None:
    info = ZipInfo(name, date_time=(2026, 1, 1, 0, 0, 0))
    info.compress_type = ZIP_DEFLATED
    info.external_attr = 0o644 << 16
    package.writestr(info, payload)


def _private_key(check: bool, env_name: str) -> Ed25519PrivateKey:
    if check:
        return Ed25519PrivateKey.generate()
    encoded = str(os.getenv(env_name) or "").strip()
    if not encoded:
        raise SystemExit(f"{env_name} must contain a base64-encoded PEM Ed25519 private key")
    try:
        loaded = serialization.load_pem_private_key(
            base64.b64decode(encoded, validate=True), password=None
        )
        if not isinstance(loaded, Ed25519PrivateKey):
            raise TypeError("key is not Ed25519")
        return loaded
    except (TypeError, ValueError) as exc:
        raise SystemExit(f"{env_name} is not a valid Ed25519 private key") from exc


def build(output_dir: Path, *, check: bool, env_name: str, key_id: str) -> tuple[Path, Path]:
    source = json.loads(SOURCE.read_text(encoding="utf-8"))
    version = source["identity"]["version"]
    release_ref = str(os.getenv("GITHUB_REF_NAME") or "").strip()
    expected_ref = f"experience-solar-energy-v{version}"
    # Ordinary CI runs set GITHUB_REF_NAME to the branch name. Only production
    # builds are tag-bound; --check intentionally uses an ephemeral key and
    # validates packaging without pretending to publish an artifact.
    if not check and release_ref and release_ref != expected_ref:
        raise SystemExit(
            f"release ref {release_ref!r} does not match package version; expected {expected_ref!r}"
        )

    archive = _archive(source)
    private_key = _private_key(check, env_name)
    manifest = {
        **source,
        "artifact": {
            "digest": f"sha256:{hashlib.sha256(archive).hexdigest()}",
            "size_bytes": len(archive),
            "media_type": "application/vnd.piphi.widget-package+zip",
            "key_id": key_id,
            "signature": None,
        },
    }
    signing_payload = SIGNING_CONTEXT + json.dumps(
        manifest, ensure_ascii=False, separators=(",", ":"), sort_keys=True
    ).encode("utf-8")
    signature = private_key.sign(signing_payload)
    private_key.public_key().verify(signature, signing_payload)
    manifest["artifact"]["signature"] = base64.b64encode(signature).decode("ascii")

    output_dir.mkdir(parents=True, exist_ok=True)
    archive_path = output_dir / f"solaredge-solar-energy-{version}.zip"
    manifest_path = output_dir / f"solaredge-solar-energy-{version}.manifest.json"
    archive_path.write_bytes(archive)
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    public_key = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    print(f"archive={archive_path}")
    print(f"manifest={manifest_path}")
    print(f"digest={manifest['artifact']['digest']}")
    print(f"publisher_public_key={base64.b64encode(public_key).decode('ascii')}")
    return archive_path, manifest_path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, default=ROOT / "dist")
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--private-key-env", default="PIPHI_WIDGET_SIGNING_KEY_PEM_BASE64")
    parser.add_argument("--key-id", default="piphi-release-1")
    args = parser.parse_args()
    if args.check:
        with tempfile.TemporaryDirectory(prefix="piphi-solaredge-experience-") as tmp:
            build(Path(tmp), check=True, env_name=args.private_key_env, key_id=args.key_id)
    else:
        build(args.output_dir, check=False, env_name=args.private_key_env, key_id=args.key_id)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
