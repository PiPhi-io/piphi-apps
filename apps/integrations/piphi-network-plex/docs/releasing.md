# Releasing Plex and its widgets

Plex has one integration registry entry. Its manifest declares the widget
packages; the widgets do not need separate integration registry entries.
`registry/plex.json` is the submission snapshot, derived from `manifest.json`
by `python scripts/registry_entry.py` (prints JSON without modifying files).
Keep the snapshot and the central registry entry aligned when metadata changes.

The initial entry is **draft**, with zero rollout and unverified qualification.
Adding it locally does not publish the runtime or make Plex generally available.

## Validate before tagging

```sh
npm ci --ignore-scripts
npm run build
npm run validate:widgets
npm test
python -m pytest -q
python scripts/validate.py
python scripts/check_release.py v0.1.1
```

Install the Python development dependencies first (`python -m pip install
'.[dev]'`). Commit the generated widget bundles, manifests, and registry snapshot
alongside the code. The release gate checks versions, image references, registry
metadata, widget routes, and bundle integrity. The publication workflow also
rejects builds that change the committed release assets.

## Publish explicitly

1. Deploy a Core version containing the Plex media-provider gateway, widget
   artifact routes, and Widget SDK `host.queryMedia` support.
2. Review and push the integration code and an existing version tag such as
   `v0.1.1`, matching `manifest.version` and the Python package version.
3. Configure the GitHub `release` environment, preferably with required
   reviewers. Configure Docker Hub OIDC as described below; no stored Docker
   access token is required.
4. Manually run **Publish Plex release**, selecting that existing tag as
   `release_ref`. The workflow validates the code, publishes the runtime image
   for Linux amd64 and arm64, and creates a GitHub prerelease containing the
   integration manifest, registry snapshot, and widget archive. The release
   notes record the image digest.
5. Submit the central registry change for maintainer review. Follow the
   registry's qualification and promotion process before enabling rollout.
   Publication does not automatically change draft status or qualification.

### GitHub setup

The repository's `release` environment has been created. It currently has no
required-reviewer protection; configure reviewers in repository settings if an
approval gate is desired. The workflow is manual-only.

Docker Hub OIDC requires a Team or Business organization. An organization owner
or editor must create a connection in Docker Home under **Identity & auth →
OIDC connections**. Follow the [Docker OIDC setup documentation](https://docs.docker.com/enterprise/security/oidc-connections/create-manage/).

Scope the connection to this repository and release environment, and grant only
the repository access needed to push `piphinetwork/piphi-network-plex`. This job
uses an environment subject, not a tag subject. With GitHub's legacy format it
would be `repo:PiPhi-io/piphi-network-plex:environment:release`; immutable subjects
also include owner and repository IDs. Confirm the repository's actual subject
format and any customization before configuring trust. See the
[GitHub OIDC reference](https://docs.github.com/en/actions/reference/security/oidc).
Use environment protections to control who can release.

The organization already provides the non-secret Actions variable
`DOCKERHUB_OIDC_CONNECTIONID`, and GitHub confirms it is available to this
repository. The workflow uses that existing variable; no duplicate repository
or environment variable is needed. Keep Plex included in its organization
access policy. The connection's Docker-side trust and push permissions still
need to allow this workflow.

For a separate installation without the organization variable, a maintainer
can configure an environment-level connection ID instead:

```sh
gh variable set DOCKERHUB_OIDC_CONNECTIONID --repo PiPhi-io/piphi-network-plex --env release
gh variable list --repo PiPhi-io/piphi-network-plex --env release
```

The workflow file must be pushed to the default branch (`main`) before GitHub
offers manual dispatch. The release tag must include the release-ready code and
bundles. Checkout explicitly targets `refs/tags/`, and the preflight rejects
missing connection IDs and malformed version tags before installing dependencies.
`id-token: write` permits the login action to exchange GitHub's short-lived OIDC
identity for Docker credentials. The workflow has no Docker password fallback.

Do not casually rerun a published tag: the Docker image uses a version tag.
Inspect any partial publication before retrying; use a new version for changed
code. No credentials or Plex server tokens belong in registry metadata or widget
configuration.
