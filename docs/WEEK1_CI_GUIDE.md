# Week 1: Write Your Own CI Pipeline (GitHub Actions)

Goal: every push and pull request to `main` gets **linted**, **tested**, and **built
into a container image**. Pushes to `main` also **publish** the image to GitHub
Container Registry (GHCR). You'll write `.github/workflows/ci.yml` yourself. This guide
gives concepts, hints, and docs, and the reference solution is at the bottom. Try first.

---

## Step 0: Push the starter code

The repo on GitHub is empty. From this folder:

```bash
git remote add origin https://github.com/TontoBlanco/grow-room-platform.git
git branch -M main
git push -u origin main
```

(If prompted for a password, use a GitHub personal access token or `gh auth login`.)

Then make a branch for your pipeline work so you can open a PR and watch CI run:

```bash
git checkout -b ci-pipeline
```

## Step 1: Workflow anatomy

A workflow is a YAML file in `.github/workflows/`. It has:
- `name`: shown in the Actions tab
- `on`: **triggers** (which events run it)
- `jobs`: units of work; each runs on a fresh VM (`runs-on: ubuntu-latest`)
- `steps`: inside a job, either `uses:` (a prebuilt action) or `run:` (a shell command)

**Why it matters:** jobs run in parallel by default and are isolated. You control
ordering with `needs:`.

Docs: <https://docs.github.com/en/actions/writing-workflows/workflow-syntax-for-github-actions>

## Step 2: Triggers

You want it to run on pushes to `main` and on pull requests targeting `main`.

> Hint: `on:` takes `push:` and `pull_request:`, each with `branches: [main]`.

**Why:** PR runs catch problems *before* merge, and push runs on `main` produce the release image.

Docs: <https://docs.github.com/en/actions/writing-workflows/choosing-when-your-workflow-runs/events-that-trigger-workflows>

## Step 3: Lint job (ruff)

Steps: check out the code, set up Python 3.12, install dev deps, run `ruff check .` and
`ruff format --check .`.

> Hints: `actions/checkout@v4`, `actions/setup-python@v5` with `python-version: "3.12"`
> and `cache: pip`. Install with `pip install -e '.[dev]'`.

**Why:** linting is the cheapest, fastest feedback. Fail fast before spending minutes on builds.
`cache: pip` reuses downloaded packages between runs (keyed off your dependency files).

Docs: <https://github.com/actions/setup-python#caching-packages-dependencies>, <https://docs.astral.sh/ruff/integrations/>

## Step 4: Test job (pytest + coverage)

Same setup as lint, then run:

```bash
pytest --cov=sensor_service --cov-report=term-missing --cov-report=xml
```

> Stretch: add `--cov-fail-under=80` so coverage drops break the build. Upload
> `coverage.xml` with `actions/upload-artifact@v4`.

**Why:** tests are your safety net. Coverage shows what's untested. Notice the tests use
the **simulator** and a **mocked** Home Assistant, so CI never needs your tent or secrets.

## Step 5: Build and push to GHCR

This job should `needs: [lint, test]` so you never ship broken code.

Concepts:
- **GITHUB_TOKEN** is an automatic, short-lived token that Actions creates for each run.
  There's no secret to manage. You must grant it permission to write packages:
  ```yaml
  permissions:
    contents: read
    packages: write
  ```
  **Why:** least privilege. The default token can be read-only, so you grant only what the job needs.
- **Login:** `docker/login-action@v3` with `registry: ghcr.io`, `username: ${{ github.actor }}`,
  `password: ${{ secrets.GITHUB_TOKEN }}`.
- **Buildx:** `docker/setup-buildx-action@v3` enables BuildKit features like caching.
- **Tags:** `docker/metadata-action@v5` generates tags. You want:
  - the commit SHA (`type=sha`). It's immutable and traceable to exact code, which Argo CD will use later.
  - `latest` only on main (`type=raw,value=latest,enable={{is_default_branch}}`).
- **Build/push:** `docker/build-push-action@v6` with `push:` set to true **only** for pushes
  to main (hint: `${{ github.event_name == 'push' && github.ref == 'refs/heads/main' }}`).
  PRs still build, which proves the Dockerfile works, but don't publish.
- **Layer cache:** `cache-from: type=gha` and `cache-to: type=gha,mode=max` store Docker
  layers in the GitHub Actions cache, so unchanged layers (like pip installs) are skipped.
- **Image name:** GHCR requires lowercase: `ghcr.io/tontoblanco/grow-room-platform`.

Docs:
- <https://docs.github.com/en/packages/managing-github-packages-using-github-packages/publishing-and-installing-a-package-with-github-actions>
- <https://github.com/docker/build-push-action>
- <https://github.com/docker/metadata-action>
- <https://docs.docker.com/build/ci/github-actions/cache/>
- <https://docs.github.com/en/actions/security-for-github-actions/security-guides/automatic-token-authentication>

## Step 6 (optional): Image vulnerability scan

Add `aquasecurity/trivy-action` after the build to scan the image for CVEs. Start with
`exit-code: "0"` (report only), then move to `severity: CRITICAL,HIGH` and `exit-code: "1"`.

**Why:** this is the same idea as the STIG and RMF work you already do, shifted left into
the pipeline. It's a strong interview point.

Docs: <https://github.com/aquasecurity/trivy-action>

## Step 7: Test it

1. Commit `ci.yml` on your `ci-pipeline` branch, push, and open a PR. Lint, test, and build should run, but nothing gets pushed.
2. Break something on purpose (an unused import), push, and watch lint fail. Then fix it.
3. Merge the PR. On `main`, the image is pushed. Find it under your profile, then **Packages**.
4. Pull it: `docker pull ghcr.io/tontoblanco/grow-room-platform:latest`.
5. Add a status badge to the README:
   `![CI](https://github.com/TontoBlanco/grow-room-platform/actions/workflows/ci.yml/badge.svg)`

New GHCR packages are private by default. Make it public in package settings if you want recruiters to see it.

## Interview talking points

- "I wrote a three-stage pipeline, lint, test, and build, where the build is gated on
  the first two with `needs`, so broken code never produces an image."
- "Images are tagged with the commit SHA for traceability and immutability. `latest`
  only moves on main. Later, Argo CD deploys a specific SHA, not a floating tag."
- "I use the ephemeral `GITHUB_TOKEN` with least-privilege `permissions`
  (`packages: write`, `contents: read`), so no long-lived registry credentials are stored."
- "PRs build but don't push, so the Dockerfile is validated without polluting the registry."
- "Pip and BuildKit layer caching (`type=gha`) cut run time on repeat builds."
- "The service has a pluggable source, a simulator or Home Assistant. CI uses the simulator
  and mocked HTTP, so tests are deterministic and need no secrets or hardware."
- "The container runs as non-root with a healthcheck, and Trivy scans it for CVEs."

---

<details>
<summary><strong>Reference solution (open only after you've tried)</strong></summary>

```yaml
name: CI

on:
  push:
    branches: [main]
  pull_request:
    branches: [main]

permissions:
  contents: read

env:
  IMAGE_NAME: ghcr.io/tontoblanco/grow-room-platform

jobs:
  lint:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
          cache: pip
      - run: pip install -e '.[dev]'
      - run: ruff check .
      - run: ruff format --check .

  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
          cache: pip
      - run: pip install -e '.[dev]'
      - run: pytest --cov=sensor_service --cov-report=term-missing --cov-report=xml --cov-fail-under=80
      - uses: actions/upload-artifact@v4
        with:
          name: coverage
          path: coverage.xml

  build:
    needs: [lint, test]
    runs-on: ubuntu-latest
    permissions:
      contents: read
      packages: write
    steps:
      - uses: actions/checkout@v4
      - uses: docker/setup-buildx-action@v3
      - uses: docker/login-action@v3
        if: github.event_name == 'push'
        with:
          registry: ghcr.io
          username: ${{ github.actor }}
          password: ${{ secrets.GITHUB_TOKEN }}
      - id: meta
        uses: docker/metadata-action@v5
        with:
          images: ${{ env.IMAGE_NAME }}
          tags: |
            type=sha,format=long
            type=raw,value=latest,enable={{is_default_branch}}
      - uses: docker/build-push-action@v6
        with:
          context: .
          push: ${{ github.event_name == 'push' && github.ref == 'refs/heads/main' }}
          load: ${{ github.event_name == 'pull_request' }}
          tags: ${{ steps.meta.outputs.tags }}
          labels: ${{ steps.meta.outputs.labels }}
          cache-from: type=gha
          cache-to: type=gha,mode=max
      - name: Scan image (report only)
        uses: aquasecurity/trivy-action@master
        with:
          image-ref: ${{ env.IMAGE_NAME }}:sha-${{ github.sha }}
          severity: CRITICAL,HIGH
          exit-code: "0"
```

Note: pin `trivy-action` to a release tag rather than `master` in real use (check its releases page).

</details>
