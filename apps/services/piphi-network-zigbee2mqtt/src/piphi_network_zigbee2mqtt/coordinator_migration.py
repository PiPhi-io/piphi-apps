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

# These records represent migration paths exercised by the sidecar recovery suite.
# Adding one is a code-reviewed compatibility decision, not caller-provided evidence.
GOVERNED_COMPATIBILITY_RECORDS = {
    "ember-same-family-v1": {"family": "ember", "backup_format": 2},
    "zstack-same-family-v1": {"family": "zstack", "backup_format": 2},
    "deconz-same-family-v1": {"family": "deconz", "backup_format": 2},
    "zigate-same-family-v1": {"family": "zigate", "backup_format": 2},
}


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
    if request.compatibility_evidence:
        raise ValueError("Free-form migration compatibility evidence is not accepted.")
    if request.source_adapter_family != request.target_adapter_family:
        raise ValueError("Coordinator migration is restricted to governed same-family records.")
    record = GOVERNED_COMPATIBILITY_RECORDS.get(request.compatibility_record_id)
    if record is None:
        raise ValueError("Coordinator migration compatibility record is not governed or tested.")
    if record["family"] != request.source_adapter_family or record["backup_format"] != metadata.get(
        "format"
    ):
        raise ValueError("Coordinator migration compatibility record does not match the backup.")
    target_probe = probe(request.target_coordinator_port)
    if not target_probe.available:
        raise ValueError(target_probe.message or "Target coordinator is unavailable or in use.")
    if not target_probe.exclusive_verified:
        raise ValueError("Target coordinator exclusivity could not be verified.")
    plan_id = migration_plan_id(request)
    return CoordinatorMigrationPlanResponse(
        plan_id=plan_id,
        compatible=True,
        target_available=True,
        source_adapter_family=request.source_adapter_family,
        target_adapter_family=request.target_adapter_family,
        target_coordinator_identity=request.target_coordinator_identity.strip(),
        target_coordinator_port=request.target_coordinator_port.strip(),
        compatibility_basis="governed_same_family_record",
        compatibility_record_id=request.compatibility_record_id,
        steps=[
            "Verify the selected backup and compatibility metadata.",
            "Probe and exclusively claim the target coordinator.",
            "Create a rollback backup of the current Zigbee2MQTT data.",
            "Restore the verified network backup.",
            "Rewrite configuration for the target coordinator.",
            "Restart and verify Zigbee2MQTT before removing the rollback backup.",
        ],
        warnings=[],
    )


def migration_plan_id(request: CoordinatorMigrationPlanRequest) -> str:
    payload = request.model_dump(
        mode="json",
        exclude={"coordinator_stop_authority", "stopped_coordinator_evidence"},
    )
    for field in ("target_coordinator_identity", "target_coordinator_port"):
        payload[field] = str(payload[field]).strip()
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return f"sha256:{hashlib.sha256(canonical).hexdigest()}"
