#!/usr/bin/env python3
from __future__ import annotations

import asyncio
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from piphi_network_tp_link.lib.qualification import (
    load_local_env,
    qualify_read_only,
    write_private_report,
)

ENV_PATH = ROOT / ".qualification.env"
REPORT_PATH = ROOT / ".qualification-results" / "read-only-report.json"


async def main() -> int:
    settings = load_local_env(ENV_PATH)
    if settings.get("PIPHI_TP_LINK_RUN_HARDWARE") != "1":
        raise SystemExit("Set PIPHI_TP_LINK_RUN_HARDWARE=1 in .qualification.env")
    host = settings.get("PIPHI_TP_LINK_QUALIFICATION_HOST", "").strip()
    if not host:
        raise SystemExit("PIPHI_TP_LINK_QUALIFICATION_HOST is required")
    username = settings.get("PIPHI_TP_LINK_QUALIFICATION_USERNAME") or None
    password = settings.get("PIPHI_TP_LINK_QUALIFICATION_PASSWORD") or None
    if bool(username) != bool(password):
        raise SystemExit("username and password must be supplied together")
    report = await qualify_read_only(
        host=host,
        username=username,
        password=password,
        samples=int(settings.get("PIPHI_TP_LINK_QUALIFICATION_SAMPLES", "3")),
    )
    expected_model = settings.get("PIPHI_TP_LINK_EXPECTED_MODEL", "").strip()
    observed_model = str(report["device"].get("model") or "")
    if expected_model and observed_model != expected_model:
        raise SystemExit(
            f"observed model does not match PIPHI_TP_LINK_EXPECTED_MODEL: {observed_model!r}"
        )
    write_private_report(report, REPORT_PATH)
    print(f"read_only_qualification=passed report={REPORT_PATH}")
    print(f"model={observed_model or 'unknown'} samples={report['sample_count']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
