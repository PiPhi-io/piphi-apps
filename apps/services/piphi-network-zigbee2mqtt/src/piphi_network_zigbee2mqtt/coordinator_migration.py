from __future__ import annotations

import hashlib
import json
from collections.abc import Callable

from .bridge_models import (
    CoordinatorMigrationPlanRequest,
    CoordinatorMigrationPlanResponse,
    CoordinatorProbeResponse,
)
from .network_backup import inspect_network_backup


def plan_coordinator_migration(
    request: CoordinatorMigrationPlanRequest,
    *,
    probe: Callable[[str], CoordinatorProbeResponse],
) -> CoordinatorMigrationPlanResponse:
    metadata = inspect_network_backup(request.backup_path, request.backup_sha256)
    backup_family = str(metadata.get("adapter_family") or "unknown").strip().lower()
    if backup_family == "unknown" or backup_family != request.source_adapter_family:
        raise ValueError(
            "Migration source adapter family does not match the verified backup metadata."
        )
    same_family = request.source_adapter_family == request.target_adapter_family
    evidence = (request.compatibility_evidence or "").strip()
    if not same_family and not evidence:
        raise ValueError(
            "Cross-family coordinator migration requires explicit compatibility evidence."
        )
    target_probe = probe(request.target_coordinator_port)
    if not target_probe.available:
        raise ValueError(target_probe.message or "Target coordinator is unavailable or in use.")
    if not target_probe.exclusive_verified:
        raise ValueError("Target coordinator exclusivity could not be verified.")
    basis = "same_family" if same_family else "explicit_evidence"
    plan_id = migration_plan_id(request)
    warnings = []
    if not same_family:
        warnings.append(
            "Cross-family migration is accepted only for the supplied evidence reference; "
            "device repair may still be required."
        )
    return CoordinatorMigrationPlanResponse(
        plan_id=plan_id,
        compatible=True,
        target_available=True,
        source_adapter_family=request.source_adapter_family,
        target_adapter_family=request.target_adapter_family,
        target_coordinator_identity=request.target_coordinator_identity.strip(),
        target_coordinator_port=request.target_coordinator_port.strip(),
        compatibility_basis=basis,
        steps=[
            "Verify the selected backup and compatibility metadata.",
            "Probe and exclusively claim the target coordinator.",
            "Create a rollback backup of the current Zigbee2MQTT data.",
            "Restore the verified network backup.",
            "Rewrite configuration for the target coordinator.",
            "Restart and verify Zigbee2MQTT before removing the rollback backup.",
        ],
        warnings=warnings,
    )


def migration_plan_id(request: CoordinatorMigrationPlanRequest) -> str:
    payload = request.model_dump(mode="json")
    payload["compatibility_evidence"] = (request.compatibility_evidence or "").strip() or None
    for field in ("target_coordinator_identity", "target_coordinator_port"):
        payload[field] = str(payload[field]).strip()
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return f"sha256:{hashlib.sha256(canonical).hexdigest()}"
