# Home Assistant parity portfolio program

This directory is the durable control record for the PiPhi-owned integration,
sidecar, and platform-service audit. Home Assistant is the quality benchmark;
the objective is comparable resilience, security, privacy, setup UX,
documentation, testing, and release discipline **plus useful functionality**.
It is not a requirement to copy every Home Assistant feature.

## Scope

- Include every registry package owned by `PiPhi-io` and represented under
  `apps/integrations` or `apps/services`.
- Exclude widgets, third-party or unowned entries, and the completed camera
  stream/WebRTC/Wyze broker batch.
- A direct Home Assistant comparator is used when the architecture matches.
  Otherwise the ledger records an architectural analogue or the general
  Integration Quality Scale rather than claiming false parity.
- Never use real accounts, providers, private data, physical devices, browser
  hardware, firmware, or field qualification in this program.

The generated [`inventory.json`](inventory.json) records the exact source and
registry revisions, package folder, release and immutable image references,
governance posture, comparator, and existing audit evidence for every package.
[`gap-matrix.md`](gap-matrix.md) is the prioritized remediation queue.

## Refreshing the inventory

Fetch both repositories, then run:

```bash
python3 scripts/build_portfolio_audit.py \
  --registry /path/to/piphi-nework-registry/registry.json \
  --registry-revision "$(git -C /path/to/piphi-nework-registry rev-parse HEAD)"
```

The generator fails if an in-scope package is missing from the registry or has
no explicit Home Assistant comparator. Release-verification booleans remain
false until the exact published digest is independently inspected; the
existence of a tag or digest in metadata is not evidence of labels, SBOM,
provenance, attestations, platforms, or non-root execution.

## Package lifecycle

1. Audit source, tests, docs, manifest, registry entry, and current HA primary
   sources. Record implemented, planned, excluded, and missing functionality.
2. Prioritize critical/security findings, then reliability, usability, and
   meaningful functionality. Do not promote a scaffold by adding only prose.
3. Remediate a reviewable package batch with behavior/contract-focused tests,
   synthetic fixtures, failure injection, and mocked protocol boundaries.
4. Open a source PR and merge only after required checks are green and review
   is safe.
5. Publish an immutable `linux/amd64` + `linux/arm64` GHCR release. Verify the
   exact digest, OCI labels, SBOM, provenance, attestations, and hardened
   non-root execution.
6. Update the registry through a separate PR with that exact digest. Preserve
   publication status, qualification status, and rollout percentage.

Production rollout, qualification, and governance promotion are separate
decisions and are never implied by source publication or registry sync.

## Stop conditions

Stop for destructive changes, ambiguous product behavior, unavailable release
credentials, provider/legal authorization questions, or any publication,
qualification, or rollout promotion decision.
