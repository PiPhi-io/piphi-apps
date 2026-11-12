# Release

This project prepares two independently versioned release artifacts: the
SolarEdge runtime image and the SolarEdge Solar Energy experience package.

Before cutting a release:

- Keep `pyproject.toml`, `manifest.json`, runtime settings, and both image fields on the same release version.
- Set `runtime.linux.container.image` to the final registry image.
- Set `maintainer.name` and `maintainer.website` to the publishing owner.
- Run the local validation and conformance tests.
- Run `pdm run python scripts/build_experience.py --check`.
- Run `piphi-network-create publish-check -C .` from this project.

The runtime workflow is triggered manually from GitHub Actions against an
already-reviewed immutable `vX.Y.Z` tag. It validates the checked-out tag,
builds the multi-architecture image, pushes it, and creates the GitHub release;
it does not rewrite or commit release metadata.

The experience workflow runs from an `experience-solar-energy-vX.Y.Z` tag. It
requires the `PIPHI_WIDGET_SIGNING_KEY_PEM_BASE64` repository secret, builds the
deterministic archive and signed manifest, and attaches both to a GitHub release.
The package and runtime versions are independent.

Images starting with `ghcr.io/` publish to GitHub Container Registry. This
repository currently publishes to Docker Hub using GitHub Actions OIDC and
short-lived credentials; no Docker Hub password or personal access token is
stored in GitHub.

## Docker Hub OIDC setup

Docker Hub OIDC requires a Docker organization on a Team or Business
subscription. In Docker Home, open the `piphinetwork` organization, go to
**Identity & auth → OIDC connections**, create a GitHub connection, restrict
its ruleset to this repository and the release workflow/default branch, and
copy the generated connection ID.

Configure these GitHub repository variables under **Settings → Secrets and
variables → Actions → Variables**:

- `DOCKERHUB_ORGANIZATION`: `piphinetwork`
- `DOCKERHUB_OIDC_CONNECTIONID`: the connection ID copied from Docker Hub

The release job grants only `contents: write` and `id-token: write` and uses
`docker/login-action@v4` to exchange GitHub's signed OIDC token for a
short-lived Docker Hub access token.

Current image target:

```text
piphinetwork/piphi-network-solaredge:0.2.2
```
