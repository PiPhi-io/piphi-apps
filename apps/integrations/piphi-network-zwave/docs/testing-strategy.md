# Layered protocol-runtime testing strategy

**Design snapshot:** 2026-11-26  
**Reference revisions:** Home Assistant Core
[`f06694954765bf246f9317458d3a9fb917b9f04c`](https://github.com/home-assistant/core/tree/f06694954765bf246f9317458d3a9fb917b9f04c),
`zwave-js-server-python`
[`6ddab45f8fc93c45c47e866dc5909be21a7a1511`](https://github.com/home-assistant-libs/zwave-js-server-python/tree/6ddab45f8fc93c45c47e866dc5909be21a7a1511),
and PiPhi apps `e8b6979`.

## Purpose

This document defines a protocol-neutral testing architecture for PiPhi runtime
integrations and applies it first to the coupled `piphi-network-zwave` parent and
`piphi-zwave-js-sidecar` service. It is a design and migration plan, not a claim
that the proposed shared TestKit APIs already exist.

The goal is to exercise the real runtime lifecycle without a physical device:

1. load a serialized protocol fixture;
2. configure the real application through its authenticated route;
3. assert discovered entities and initial state;
4. issue a real runtime command and inspect the exact protocol command;
5. inject a protocol event and assert state and Core delivery;
6. reload the application and prove stable identity; and
7. deconfigure and prove cleanup.

The design deliberately separates reusable runtime behavior from protocol
semantics. Shared TestKits own application lifecycle, runtime authentication,
Core capture, transition tracing, assertions, and cleanup. A protocol adapter
owns Z-Wave snapshots, value IDs, events, commands, and device fixtures.

## What Home Assistant's architecture teaches

Home Assistant does not obtain Z-Wave confidence from one all-purpose fake.
Its tests are layered:

- `zwave-js-server-python` tests transport commands and builds its real
  `Driver`, `Node`, and value models from serialized state fixtures. See its
  [fixtures](https://github.com/home-assistant-libs/zwave-js-server-python/tree/6ddab45f8fc93c45c47e866dc5909be21a7a1511/tests/fixtures)
  and
  [`conftest.py`](https://github.com/home-assistant-libs/zwave-js-server-python/blob/6ddab45f8fc93c45c47e866dc5909be21a7a1511/tests/conftest.py).
- Home Assistant patches the client boundary while running its real config
  entry, platform, entity, and registry machinery. Its shared Z-Wave fixtures
  instantiate the real client-library models rather than replacing them with
  integration-shaped dictionaries. See HA's
  [`conftest.py`](https://github.com/home-assistant/core/blob/f06694954765bf246f9317458d3a9fb917b9f04c/tests/components/zwave_js/conftest.py).
- Platform suites assert discovery, state changes caused by incoming events,
  and exact outgoing commands. Representative examples are
  [`test_switch.py`](https://github.com/home-assistant/core/blob/f06694954765bf246f9317458d3a9fb917b9f04c/tests/components/zwave_js/test_switch.py)
  and
  [`test_sensor.py`](https://github.com/home-assistant/core/blob/f06694954765bf246f9317458d3a9fb917b9f04c/tests/components/zwave_js/test_sensor.py).
- Setup, unload, migration, service validation, permissions, events, and
  failures remain dedicated test concerns; they are not hidden inside platform
  fixtures. See
  [`test_init.py`](https://github.com/home-assistant/core/blob/f06694954765bf246f9317458d3a9fb917b9f04c/tests/components/zwave_js/test_init.py),
  [`test_services.py`](https://github.com/home-assistant/core/blob/f06694954765bf246f9317458d3a9fb917b9f04c/tests/components/zwave_js/test_services.py),
  and
  [`test_events.py`](https://github.com/home-assistant/core/blob/f06694954765bf246f9317458d3a9fb917b9f04c/tests/components/zwave_js/test_events.py).

At the pinned revisions, the HA Z-Wave suite contains 94 serialized fixture
files and 34 top-level test modules. The useful lesson is the shape and breadth
of the layers, not the raw count and not a requirement to copy HA fixtures.

## PiPhi baseline and gaps

PiPhi already has the foundations:

- Node TestKit `0.1.0` provides `MockCoreServer`, request builders,
  telemetry/event/entity assertions, `createTestRuntimeHarness`, and background
  task flushing.
- Python TestKit `0.2.x` provides `MockCoreServer`, config/header builders, and
  telemetry/event/entity/state assertions.
- The sidecar accepts an injectable `DriverSessionFactory`; the parent accepts
  an injectable sidecar client factory.
- Current Z-Wave suites cover route authentication, snapshots, exact write
  translation, replay gaps, transactional configuration, administration, NVM
  simulation, and Core delivery.

The missing shared layer is application-level orchestration. Tests still
manually wire Core URLs, construct in-process HTTP clients, poll background
work, restore global factories, deconfigure registries, and close servers.
Python also lacks the starter-harness helper already present in the Node
TestKit. Protocol fixtures are integration-local and have no common discovery,
validation, scenario, or trace format.

## Target test layers

| Layer | Executes | Owned by | Z-Wave example |
|---|---|---|---|
| 1. Pure model | Parsers, normalization, identity, policy | Integration or protocol library | Z-Wave value metadata becomes switch/meter capabilities |
| 2. Protocol transport | Real protocol client/model against scripted messages | Protocol adapter/TestKit | Driver command result and event normalization |
| 3. Fixture corpus | Serialized devices and protocol states | Protocol adapter | Switch + meter node snapshot and value update |
| 4. Runtime application | Real routes, auth, lifecycle, background work, Core clients | Shared Runtime TestKit | Configure parent, discover entity, command, event, reload, cleanup |
| 5. Failure matrices | Auth, timeout, disconnect, malformed data, replay, replacement | Shared matrix + adapter scripts | Sidecar 401, snapshot timeout, replay gap, rejected set value |
| 6. Physical qualification | Controller, RF, security, firmware, NVM, real devices | Hardware qualification program | S2 inclusion and sleeping-node behavior on named hardware |

Layers 1–5 are deterministic software evidence. They do not satisfy layer 6.

## Proposed shared abstractions

The names below describe the cross-language contract. Node may use camelCase
and Python snake_case, but both implementations must consume the same JSON
fixtures and pass the same conformance scenarios.

### `RuntimeAppHarness`

`RuntimeAppHarness` wraps a real in-process application and the existing mock
Core. It does not know Z-Wave.

```text
RuntimeAppHarness.start(options) -> harness

options:
  app                 framework adapter for ASGI, Fastify, or Express
  integration_id      expected PiPhi integration identifier
  config_id           deterministic test configuration ID
  container_id        deterministic runtime owner ID
  internal_token      fake test-only token
  bind_core(app, url) callback that points real SDK clients at Mock Core
  reset_app?           callback used to emulate a process reload
  cleanup?             idempotent integration cleanup callback

harness.config(extra)                 authenticated POST /config
harness.request(method, path, body?)   authenticated application request
harness.command(command)               command with unique idempotency key
harness.entities()                     validated entities response
harness.state()                        current runtime state
harness.wait_until(predicate, timeout) bounded background-work wait
harness.reload()                       stop/start app, preserving configured data
harness.trace                          ordered lifecycle/request/Core transitions
harness.stop()                         cleanup app, Core, tasks, globals, temp data
```

Required behavior:

- generate valid runtime headers and config envelopes through existing builder
  APIs rather than duplicating contract shapes;
- start and stop `MockCoreServer` and expose existing Core assertions;
- fail after bounded waits and include the transition trace in the error;
- register cleanup immediately after each resource starts and unwind in reverse
  order, including after partial setup failures;
- isolate configuration stores, ledgers, ports, environment variables, and
  mutable factories per test;
- support explicit unauthenticated requests for authorization tests without
  weakening the default authenticated client; and
- never infer protocol-specific success from an HTTP 2xx response.

The existing Node `createTestRuntimeHarness` should be evolved or composed,
not replaced. Python receives the equivalent lifecycle primitive.

### `ScriptedProtocolBackend`

`ScriptedProtocolBackend` is a protocol-neutral deterministic state machine.
It stores opaque JSON payloads and delegates protocol interpretation to an
adapter.

```text
backend = ScriptedProtocolBackend(adapter, scenario)

backend.start()
backend.snapshot()                         next scripted snapshot
backend.execute(operation, payload)        record and match exact operation
backend.emit(event_id | event_payload)     inject an incoming event
backend.fail(operation, failure)           arm one bounded failure
backend.calls(operation?)                  immutable recorded calls
backend.assert_consumed()                  no required step left unmatched
backend.reset() / backend.stop()
```

The shared engine owns sequencing, call recording, barriers, bounded delays,
one-shot failures, and mismatch diagnostics. The adapter owns:

- converting a corpus device into the production client's model;
- translating generic backend operations into a sidecar client or driver
  interface;
- applying protocol events to protocol state; and
- comparing protocol commands, including protocol-specific identifiers.

For Z-Wave there are two adapters over the same corpus:

1. `ZWaveDriverAdapter` implements the sidecar's `DriverSessionFactory` seam and
   checks `DriverCommand` objects.
2. `ZWaveSidecarAdapter` implements the parent's sidecar-client seam and checks
   authenticated snapshot/event/command behavior.

The first vertical slice may use these adapters in-process. A later contract
suite should run the parent against the real sidecar HTTP app to prove the seam
without serial hardware.

### `ProtocolFixtureCorpus`

`ProtocolFixtureCorpus` discovers and validates language-neutral JSON. Shared
code understands document metadata and scenario mechanics only; adapters
validate the opaque `protocol` sections.

```text
corpus = ProtocolFixtureCorpus.open(path, adapter)
corpus.devices(tags?)
corpus.scenarios(tags?)
corpus.device(id)
corpus.scenario(id)
corpus.validate()
```

Corpus rules:

- fixtures are immutable inputs; scenario execution deep-copies state;
- every document has a schema version, stable ID, provenance, and tags;
- synthetic data is labelled `synthetic`; captured data records its source and
  sanitization method;
- secrets, full Home IDs, DSKs, network keys, raw NVM, and user data are
  forbidden by corpus validation;
- ordering is explicit where it matters and ignored where the production
  contract defines a set; and
- Node and Python must load the same files and produce the same normalized
  conformance trace.

## Language-neutral fixture schemas

JSON Schema documents should eventually live in the shared TestKit repository
and be versioned independently. The first implementation can validate these
fields directly before extracting formal schemas.

### Device document

```json
{
  "schema_version": "piphi.protocol-device.v1",
  "id": "zwave.switch-meter.synthetic.v1",
  "protocol": "zwave",
  "provenance": {
    "kind": "synthetic",
    "source": "PiPhi Z-Wave contract",
    "sanitized": true
  },
  "tags": ["switch", "meter", "mains"],
  "initial": {
    "snapshot": {
      "schema_version": "piphi.zwave.snapshot.v1",
      "controller": {},
      "nodes": []
    }
  },
  "protocol_data": {
    "driver_model": {}
  }
}
```

Only `schema_version`, `id`, `protocol`, `provenance`, `tags`, and `initial` are
shared semantics. The Z-Wave adapter owns the contents of `snapshot` and
`protocol_data`.

### Scenario document

```json
{
  "schema_version": "piphi.protocol-scenario.v1",
  "id": "zwave.switch-meter.vertical-slice.v1",
  "protocol": "zwave",
  "device_ref": "zwave.switch-meter.synthetic.v1",
  "tags": ["vertical-slice", "command", "event", "reload"],
  "steps": [
    {"id": "configure", "do": "runtime.configure", "input": {}},
    {"id": "initial-entity", "assert": "runtime.entity", "expect": {}},
    {"id": "switch-on", "do": "runtime.command", "input": {}},
    {"id": "driver-write", "assert": "protocol.command", "expect": {}},
    {"id": "reported-on", "do": "protocol.emit", "input": {}},
    {"id": "final-state", "assert": "runtime.state", "expect": {}},
    {"id": "core-event", "assert": "core.event", "expect": {}},
    {"id": "reload", "do": "runtime.reload"},
    {"id": "stable-id", "assert": "runtime.entity", "expect": {}},
    {"id": "cleanup", "do": "runtime.deconfigure"}
  ]
}
```

Shared step kinds are restricted to runtime lifecycle, Core capture, protocol
input/output, and barriers. Protocol payloads under `input` and `expect` remain
opaque to the shared runner. Unknown step kinds fail validation.

### Conformance trace

Both languages emit the same normalized trace for shared runner tests:

```json
{
  "schema_version": "piphi.protocol-trace.v1",
  "scenario_id": "zwave.switch-meter.vertical-slice.v1",
  "outcome": "passed",
  "transitions": [
    {"step_id": "configure", "kind": "runtime", "outcome": "passed"},
    {"step_id": "driver-write", "kind": "protocol", "outcome": "passed"}
  ],
  "cleanup": {"attempted": true, "outcome": "passed"}
}
```

Durations and framework-specific diagnostics may be attached, but conformance
comparison excludes nondeterministic ports, timestamps, and durations.

## First Z-Wave vertical slice

The initial corpus device is one synthetic, ready node exposing Binary Switch
command class 37 and Meter command class 50. It uses fixed fake 64-character
network, controller, node, and value hashes.

The scenario must prove this sequence:

1. Start mock Core, the scripted Z-Wave adapter, and the real parent ASGI app.
2. Configure `home-network` with valid owner headers. The adapter returns the
   initial snapshot with switch `false` and power `46.7 W`.
3. Assert one stable endpoint entity, switch and power capabilities, the
   advertised `set_switch` command, initial state, and no secret material.
4. Send authenticated `set_switch(true)` with a unique idempotency key.
5. Assert exactly one protocol command:

   ```json
   {
     "command": "set_value",
     "params": {
       "node_id": 2,
       "value_id": {
         "command_class": 37,
         "endpoint": 0,
         "property": "targetValue"
       },
       "value": true
     }
   }
   ```

6. Assert state remains observation-driven until the backend emits a
   `value updated` event for `currentValue=true`.
7. Inject that event; wait for the real supervisor to consume it; assert final
   switch state and the exact redacted Core event/telemetry contract.
8. Reload the application while retaining its isolated persisted config.
   Return a fresh snapshot and assert the entity ID is unchanged and no second
   command was issued.
9. Deconfigure, stop every background task, close clients/Core, restore injected
   factories and environment, and assert no active config or unconsumed script
   step remains.

This replaces no existing test initially. It becomes the canonical end-to-end
scenario after it is green in both the direct parent adapter and the real
parent-to-sidecar HTTP contract suite.

## Required matrices beyond the vertical slice

Keep matrices declarative and small enough that each failure has one meaning.

### Lifecycle pack

- initial configure, idempotent sync, deconfigure;
- persisted restart and stable identity;
- failed initial setup leaves no entry;
- failed replacement preserves the last-known-good entry;
- dependency disconnect/reconnect; and
- sidecar stream change and replay-gap snapshot reconciliation.

### Authorization pack

- liveness is public and operational routes are denied anonymously;
- correct owner headers are accepted;
- wrong container or token is rejected;
- sidecar bearer-token omission/mismatch is rejected; and
- admin actions require their explicit confirmations.

### Failure pack

- malformed snapshot/event, unsupported schema, and oversized response;
- timeout before acceptance versus uncertain outcome after dispatch;
- protocol command rejection and unconfirmed write result;
- Core 4xx, 5xx, and timeout through existing mock-Core controls;
- duplicate and out-of-order event sequences; and
- cleanup after each partial startup point.

Protocol adapters add domain-specific cases, such as sleeping nodes and Z-Wave
`SetValueResult` values, without adding those concepts to shared TestKits.

## Ownership boundaries

| Concern | Shared Runtime TestKit | Protocol adapter/corpus | Application test |
|---|---:|---:|---:|
| App start/stop and authenticated requests | Owns | — | Supplies framework binding |
| Mock Core and delivery assertions | Owns | — | Selects expected domain event |
| Waits, trace, teardown, temp stores | Owns | — | May add app cleanup callback |
| Script sequencing and call recording | Owns | Interprets payload | Selects scenario |
| Snapshot/event/command meaning | — | Owns | Asserts product mapping |
| Device corpus and protocol provenance | — | Owns | Selects representative device |
| Entity/capability mapping | Generic shape only | Supplies protocol input | Owns expected PiPhi behavior |
| Physical interoperability | — | — | Out of scope; qualification rig owns it |

Shared libraries must not import `zwave-js`, Z-Wave command-class constants, or
the parent/sidecar packages.

## Node/Python parity contract

Parity means equivalent observable behavior, not identical implementation:

1. publish the fixture schemas and conformance scenarios with the TestKit
   release;
2. run the same valid and invalid corpus documents in both TestKit repositories;
3. compare normalized traces as golden JSON;
4. require matching cleanup guarantees and timeout semantics;
5. retain idiomatic framework adapters (`app.inject` for Fastify and ASGI
   transport/lifespan support for Python); and
6. version schema changes independently and support at least the current schema
   in both languages before an application adopts it.

Do not block the Z-Wave prototype on publishing both packages. Prototype the
API integration-locally, then move only proven protocol-neutral behavior into
the shared TestKits with conformance fixtures.

## Phased implementation and migration

### Phase 0 — design and corpus seed

- accept this ownership model;
- extract the current switch/meter snapshot and realistic event into sanitized
  device/scenario documents; and
- add fixture validation that rejects known Z-Wave secret fields.

### Phase 1 — Z-Wave local prototype

- implement a small integration-local scripted backend and Z-Wave adapters;
- add the first parent vertical slice using the real ASGI app and Mock Core;
- add the corresponding sidecar driver scenario; and
- emit a normalized trace and prove teardown after an injected failure.

Existing `FakeSidecarClient` and `createMockDriverFactory` tests remain while the
prototype proves the API.

### Phase 2 — shared TestKit extraction

- add `RuntimeAppHarness` and `ScriptedProtocolBackend` to Node TestKit;
- add equivalent Python APIs, including starter/application lifecycle support;
- publish schemas, a corpus loader, and cross-language conformance fixtures; and
- migrate the Z-Wave prototype to released TestKit versions.

### Phase 3 — real coupled software path

- run the real parent against the real sidecar HTTP application;
- retain only the serial-driver boundary as scripted;
- cover authenticated snapshots, replay, exact commands, Core delivery, reload,
  and process-order failure; and
- execute the lifecycle, authorization, and failure packs in CI.

### Phase 4 — corpus growth and reuse

- add lock, thermostat, multilevel sensor, battery, dimmer, and unsupported-value
  fixtures from sanitized, traceable sources;
- adopt the shared harness in another protocol integration to prove neutrality;
  and
- remove integration-local lifecycle helpers only after equivalent shared tests
  are green and diagnostics are at least as useful.

No phase publishes, tags, changes marketplace verification, or claims hardware
qualification by itself.

## Acceptance gates

The design is implemented when:

- the first scenario runs through real authenticated runtime routes;
- it asserts exact protocol output and observation-driven state input;
- mock Core captures the expected redacted output;
- reload preserves entity identity and cleanup leaves no tasks/config/temp data;
- Node and Python pass the same corpus/trace conformance fixtures;
- lifecycle, authorization, and failure packs are deterministic in CI; and
- documentation and test names call the result simulator/fixture contract
  confidence, not device or interoperability qualification.

## Confidence boundary

These tests can establish application lifecycle, auth, parent/sidecar contract,
normalization, identity, command translation, replay, failure, redaction, and
Core-delivery behavior for the supplied fixtures. They cannot establish:

- USB/serial controller compatibility or hotplug behavior;
- RF range, interference, routing, latency, or mesh healing;
- S0/S2 negotiation, DSK interaction, or secure inclusion on hardware;
- sleeping-device timing, wake-up queues, or device firmware quirks;
- real `SetValueResult` behavior across devices;
- controller firmware, NVM format, backup/restore, or migration compatibility;
  or
- a supported-device matrix, soak result, marketplace verification, or Home
  Assistant parity.

Those claims require a separately recorded physical qualification plan with
named controller, firmware, device, security class, topology, procedure, and
result evidence. This boundary is consistent with the existing
[Home Assistant quality comparison](home-assistant-quality-comparison.md).

## Primary-source index

- Home Assistant Z-Wave integration source and tests at the pinned revision:
  [component](https://github.com/home-assistant/core/tree/f06694954765bf246f9317458d3a9fb917b9f04c/homeassistant/components/zwave_js),
  [tests](https://github.com/home-assistant/core/tree/f06694954765bf246f9317458d3a9fb917b9f04c/tests/components/zwave_js), and
  [fixtures](https://github.com/home-assistant/core/tree/f06694954765bf246f9317458d3a9fb917b9f04c/tests/components/zwave_js/fixtures).
- `zwave-js-server-python` at the pinned revision:
  [tests](https://github.com/home-assistant-libs/zwave-js-server-python/tree/6ddab45f8fc93c45c47e866dc5909be21a7a1511/tests),
  [fixtures](https://github.com/home-assistant-libs/zwave-js-server-python/tree/6ddab45f8fc93c45c47e866dc5909be21a7a1511/tests/fixtures), and
  [mock server](https://github.com/home-assistant-libs/zwave-js-server-python/blob/6ddab45f8fc93c45c47e866dc5909be21a7a1511/tests/mock_server.py).
- PiPhi evidence:
  [current parent vertical slice](../tests/test_vertical_slice.py),
  [parent fake sidecar](../tests/conftest.py),
  [sidecar mock driver](../../../services/piphi-zwave-js-sidecar/tests/helpers/mock-driver.ts),
  [sidecar Core delivery test](../../../services/piphi-zwave-js-sidecar/tests/core-delivery.test.ts),
  [sidecar lifecycle recovery test](../../../services/piphi-zwave-js-sidecar/tests/state-recovery.test.ts), and
  [runtime contract](contract.md).
