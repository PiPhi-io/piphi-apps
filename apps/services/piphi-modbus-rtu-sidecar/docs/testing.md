# Testing Architecture

The sidecar test architecture adapts patterns from Home Assistant Core's
Modbus tests at commit
[`a0f0cf28`](https://github.com/home-assistant/core/tree/a0f0cf28fea4e1dfea7937305808a3b5414111fd/tests/components/modbus).
It does not copy Home Assistant's entity-platform model: this package owns only
serial transport and lifecycle, while the parent owns device semantics.

## Test seams

| Seam | Evidence | Catches | Does not claim |
|---|---|---|---|
| Authenticated HTTP contract | ASGI requests for config, snapshot, refresh, constrained writes, deconfigure, and failed setup | Auth, validation, ghost-state leaks, safe errors, parent contract drift | Network deployment or Core availability |
| Serial wire | Real PTYs for RTU/ASCII reads and writes; malformed-frame and timing matrices | FC01–06/15/16 request bytes, CRC/LRC, framing, confirmation, and line sequencing | Physical adapters, electrical noise, or device compatibility |
| Lifecycle ownership | Scripted serial sessions for replace, restart rehydration, shutdown, and stale-last-good behavior | Candidate-before-release ordering, rollback, cleanup isolation, restoration, bounded retry outcomes | OS hotplug behavior outside the process |
| Queue and event backpressure | Deterministic blocked, saturated, failed, and replay-gap operations | One in-flight operation, capacity recovery, high-water metrics, bounded event loss | Throughput on a physical bus |

## Home Assistant patterns retained

- Shared configurable transport doubles live in `tests/conftest.py`.
- Parameterized matrices cover function codes and distinct error classes.
- Black-box HTTP and PTY tests are preferred over assertions on private helpers.
- Lifecycle tests prove ownership and cleanup, including one failing resource not
  preventing unrelated resources from closing.
- Expected wire values are protocol literals, not values recomputed by the
  implementation under test.

Every new failure mode should first be added at the narrowest applicable seam.
Cross-seam end-to-end tests remain intentionally small so a failure identifies
which contract broke.
