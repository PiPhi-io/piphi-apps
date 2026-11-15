# PiPhi integration quality scale

PiPhi marketplace quality tiers use the names and cumulative intent of Home
Assistant's Integration Quality Scale (IQS): `bronze`, `silver`, `gold`, and
`platinum`. A tier is a user-facing promise, not a measure of protocol breadth.
An integration may support a deliberately narrow device or protocol slice and
still earn a tier when that slice is honest, reliable, documented, and tested.

The upstream rules are written for code running inside Home Assistant Core.
PiPhi runtimes use an out-of-process Runtime SDK contract, so repository-specific
equivalents and exemptions must be explicit in each package's
`quality-scale.yaml`.

## Claim requirements

An app may change `marketplace.quality_tier` from `unrated` only when:

1. `quality-scale.yaml` names the upstream standard and target tier;
2. every rule through that tier is `done` or `exempt` with a reason;
3. every `done` rule links to concrete repository evidence;
4. app CI validates the checklist and the manifest claim together;
5. the capability catalog accounts for implemented, planned, and excluded scope;
6. user documentation describes setup, removal, supported behavior, automation,
   failure behavior, troubleshooting, privacy boundaries, and known limitations;
7. setup validates required dependencies before committing configuration, while
   an already configured runtime degrades and recovers without fabricating state.

Exemptions adapt framework-specific mechanics; they cannot waive the behavior a
rule protects. For example, a PiPhi runtime has no Home Assistant `ConfigEntry`,
but it must still keep runtime state out of persisted public configuration and
support deterministic removal and restart cleanup.

## Bronze mapping

The current upstream Bronze tier has 20 rules. PiPhi applies their intent as
follows:

- Home Assistant config flows map to `/ui-config`, typed `/config` validation,
  transactional dependency checks, and duplicate-safe stable config IDs.
- Home Assistant entity lifecycle and naming rules map to stable Runtime SDK
  device/entity IDs, lifecycle-owned tasks, and cleanup on deconfiguration.
- Home Assistant service setup maps to process-level Runtime SDK automation
  registration rather than per-config registration.
- Home Assistant Brands is exempt for non-Core packages; PiPhi marketplace
  publisher, compatibility, documentation, and support metadata is required.
- Documentation rules apply to the package README or linked first-party docs.

Silver and higher remain cumulative. In particular, Silver requires measured
coverage above 95%, explicit ownership, unload/reload behavior, availability and
recovery semantics, and user-facing handling of authentication failures. Gold
adds discovery, diagnostics, repairs, reconfiguration, translations, and full
user documentation. Platinum adds strict typing and fully asynchronous,
efficient dependencies where applicable.

## Review source

- Home Assistant IQS overview: <https://developers.home-assistant.io/docs/core/integration-quality-scale/>
- Home Assistant IQS rules: <https://developers.home-assistant.io/docs/core/integration-quality-scale/rules/>

The checklist must record its review date because upstream rules evolve.
