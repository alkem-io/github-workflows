# Alkemio reusable GitHub Actions workflows

Central home for the org's CI/CD workflows. Each Alkemio repo keeps only thin
caller files; the logic, the action versions, and the tool pins (golangci-lint,
sqlc, apispec, kubectl, …) live **here, once**.

## Versioning

Callers pin the mutable major tag `@v1` (org convention — no SHA-pinning).
Changes land here via PR; releases are tagged `v1.x.y` and the `v1` tag is
moved. Breaking caller-interface changes go to `v2`.

## Workflows

| File | Purpose |
|---|---|
| `go-ci.yml` | Go lint + race tests (+optional coverage threshold), optional build check, optional reviewed repository setup script, optional sqlc / OpenAPI staleness gates, optional extra build-tagged suite |
| `container-pr.yml` | Multi-arch (amd64+arm64, native runners, no QEMU) PR image to GHCR + PR-description footer reporting the image to pull |
| `container-release.yml` | Multi-arch release image to Docker Hub: digest-merge pattern, semver tags, prerelease-aware `latest`, index annotations, SBOM + provenance |
| `deploy-hetzner.yml` | Build + push `:sha` to the private registry and roll the k8s deployment (set-image mode, or full-manifest mode via `manifest-path`) |
| `contract-lint.yml` | Redocly lint for handwritten OpenAPI contracts |

Conventions: `concurrency`, triggers, and `permissions` live in the **caller**
(reusable-workflow limitation / explicitness). Pass secrets **explicitly**, not
via `secrets: inherit` — the PR-image workflow needs only the auto-provided
`GITHUB_TOKEN` (no `secrets:` block at all), and the release workflow takes
exactly `DOCKERHUB_USERNAME` + `DOCKERHUB_TOKEN`. Explicit mapping is
least-privilege and clears the zizmor/CodeRabbit `secrets-inherit` finding.

## Caller recipes

### CI (`.github/workflows/ci-test.yml`)

```yaml
name: CI — Lint & Test
on:
  push:
    branches: [develop, main]
  pull_request:
    types: [opened, synchronize, reopened]
jobs:
  ci:
    uses: alkem-io/github-workflows/.github/workflows/go-ci.yml@v1
    permissions:
      contents: read
    with:
      coverage-min: 95                             # 0 (default) reports coverage without gating
      setup-script: .scripts/ci/setup-native.sh   # omit unless committed native setup is required
      sqlc-config: db/sqlc.yaml                  # omit to skip sqlc gate
      sqlc-generated-path: internal/adapter/outbound/alkemiodb/queries
      openapi-make-target: openapi               # omit to skip OpenAPI gate
      extra-suite-tags: vips                     # omit to skip extra suite
      extra-suite-apt: libvips-dev
```

### PR image (`.github/workflows/build-push-ghcr-pr.yml`)

```yaml
name: Build & Push Container (PR)
on:
  pull_request:
    types: [opened, synchronize, reopened]
concurrency:
  group: pr-image-${{ github.event.number }}
  cancel-in-progress: true
jobs:
  image:
    uses: alkem-io/github-workflows/.github/workflows/container-pr.yml@v1
    permissions:
      contents: read
      packages: write
      pull-requests: write
    # No secrets block: the workflow uses only the auto-provided GITHUB_TOKEN.
```

### Release (`.github/workflows/build-release-docker-hub.yml`)

```yaml
name: Deploy to DockerHub
on:
  release:
    types: [published, released]
concurrency:
  group: dockerhub-release
  cancel-in-progress: false
jobs:
  release:
    uses: alkem-io/github-workflows/.github/workflows/container-release.yml@v1
    permissions:
      contents: read
      packages: write    # GHCR mirror (ghcr.io/<owner>/<repo>); Docker Hub stays primary
    secrets:
      DOCKERHUB_USERNAME: ${{ secrets.DOCKERHUB_USERNAME }}
      DOCKERHUB_TOKEN: ${{ secrets.DOCKERHUB_TOKEN }}
```

### Deploy (`.github/workflows/build-deploy-k8s-dev-hetzner.yml`)

```yaml
name: Build & Deploy to Dev on Hetzner
on:
  push:
    branches: [develop]
jobs:
  deploy:
    uses: alkem-io/github-workflows/.github/workflows/deploy-hetzner.yml@v1
    with:
      environment: dev
      # name inputs only needed when the repo deviates from the conventions
      # alkemio-<repo> / alkemio-<repo>-deployment / <repo>-registry
    secrets:
      KUBECONFIG: ${{ secrets.KUBECONFIG_SECRET_HETZNER_DEV }}
      REGISTRY_LOGIN_SERVER: ${{ secrets.REGISTRY_LOGIN_SERVER }}
      REGISTRY_USERNAME: ${{ secrets.REGISTRY_USERNAME }}
      REGISTRY_PASSWORD: ${{ secrets.REGISTRY_PASSWORD }}
```

(test/sandbox: same caller with `on: workflow_dispatch:`, `environment: test|sandbox`,
and the matching `KUBECONFIG_SECRET_HETZNER_*`. Repos shipping a full manifest
instead of patching an existing deployment add `manifest-path: manifests/...yaml`.)
