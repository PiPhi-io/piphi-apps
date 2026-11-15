# Virtual KNX qualification

This package has an opt-in end-to-end protocol test using a real `knxd` KNXnet/IP server with its dummy bus. It increases confidence without pretending to be physical gateway qualification.

## Evidence boundary

The fixture verifies that the production `XknxClient` can:

- establish automatic, explicit UDP, and explicit TCP KNXnet/IP tunnels through an independent C++ server;
- send typed DPT `1.001` and `5.001` group writes observed by another tunnel;
- receive and decode DPT `1.001`, `5.001`, and `9.001` feedback telegrams;
- send a group read and process a DPT `9.001` response; and
- stop both tunnel types cleanly.

It does **not** verify electrical KNX TP behavior, gateway firmware, multicast discovery across a real network, tunnel-slot exhaustion, KNX Secure, routing, ETS projects, or vendor interoperability. The observer uses xknx, as does the runtime, so this is not an independent DPT-codec certification. Registry qualification must remain `unverified` until physical evidence exists.

## Reproducibility

The fixture pins:

- Debian trixie slim by OCI digest;
- `knxd==0.14.73-1`; and
- the application lockfile, including `xknx==4.1.1`.

The pin and dummy-bus configuration follow the independently maintained [knx-interop v0.9.2](https://github.com/otfabric/knx-interop/tree/v0.9.2) server pattern. The repository owns the small fixture so test execution does not depend on an unpublished third-party image.

Run on Linux with Docker and the locked development environment installed:

```bash
cd apps/integrations/piphi-network-knx
./scripts/run_virtual_knx_qualification.sh
```

The script uses host networking because KNXnet/IP UDP connection negotiation carries a callback endpoint; ordinary Docker port translation would advertise an unreachable address. It starts and removes only a container named `piphi-knxd-virtual` and binds KNXnet/IP port `3671` for the duration of the test.

The normal test suite collects these scenarios but skips them unless `PIPHI_KNX_VIRTUAL_TEST=1`. The dedicated `KNX virtual qualification` workflow runs them on every relevant pull request and push to `main`.

## Interpreting a pass

A pass is software interoperability evidence for the bounded transport and DPT slice. Record the workflow URL and source commit in release evidence, but do not change hardware qualification, marketplace quality, or rollout governance from this result alone.
