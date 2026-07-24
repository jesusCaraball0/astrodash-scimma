---
title: GitHub Actions Test Gate - Plan
type: ci
date: 2026-07-24
topic: github-actions-test-gate
artifact_contract: ce-unified-plan/v1
artifact_readiness: implementation-ready
product_contract_source: ce-brainstorm
execution: code
---

# GitHub Actions Test Gate - Plan

## Goal Capsule

- **Objective:** Add a GitHub Actions workflow that runs the automated test suite on every pull request and on merge to `main`, as a required status check that blocks merging when the suite fails, configured on both the fork (`skoranda/astrodash`) and the canonical repo (`scimma/astrodash`). The workflow builds the application image and runs the existing container `TEST_MODE` target, so CI exercises the exact artifact that deploys.
- **Product authority:** Scott Koranda (maintainer).
- **Open blockers:** None. Branch protection is a repository Settings change the maintainer performs (documented here, not applied by code). The DEV/PROD rollout of the open model-registry PR is a separate track and does not gate this work.

## Product Contract

### Summary

A single GitHub Actions workflow runs the test suite on pull-request events and on pushes to `main`, and its result is made a required status check on both repos so a red run blocks the merge. It runs the suite by building the app image and executing the existing `TEST_MODE` container target (`manage.py test --exclude-tag=download`), with Docker layer caching to tame the CPU-only PyTorch build. Only the tests gate — no formatting or coverage check is added.

### Problem Frame

Nothing runs the tests automatically today. The only workflow, `docker_image_workflow.yml`, triggers solely on version tags and builds/pushes the image; no check runs on a pull request, so a PR can be merged with a red suite and the regression is found only later. The immediate goal is to close that gap before the model-registry work and future changes land in DEV and PROD.

Two things make this cheap rather than a build-out. The container already carries a self-contained CI test target: the `TEST_MODE` entrypoint runs `coverage run manage.py test --exclude-tag=download astrodash.tests users.tests`, and the suite is data-independent on its own today — no test is tagged `download` yet, so the exclude-tag is a forward-compatible guard for future data-dependent tests — so it needs no external model data or S3 credentials. And a `ci` Compose profile already wires the app and database for that target. What is missing is the GitHub Actions wrapper around it, a small adjustment so it runs on a hosted runner (an ephemeral data volume plus disabling the default data download), and the branch-protection setup that turns a passing run into a real gate.

### Key Decisions

- **Required merge gate, not just a signal.** A failing run blocks the merge via branch protection. (session-settled: user-directed — chosen over a pass/fail signal that does not block, and over gating only one repo: CI protects `main` only if it can stop a broken merge.)
- **Run the shipped container, not a re-derived environment.** The workflow builds the app image and runs the existing `TEST_MODE` target through the `ci` Compose profile. (session-settled: user-directed — chosen over a CI-native Postgres-service + pip setup: CI then tests the exact image that deploys, matching the project's Docker-first stance; GitHub Actions layer caching mitigates the CPU-torch build cost.)
- **Tests only.** No `black --check`, no coverage floor or upload. (session-settled: user-directed — chosen over tests + `black --check` and over tests + a coverage gate: keep the gate to the suite for now; the `coverage report` that `TEST_MODE` prints is incidental, not a gate.)
- **Gate both repos from one file.** The required check is configured on both `origin/main` (skoranda) and `scimma/main` (scimma), using the same identical workflow file. (session-settled: user-directed — chosen over fork-only or upstream-only.)
- **Triggers and concurrency.** `pull_request` (opened, synchronized, reopened) plus `push` to `main`, with a concurrency group that cancels a PR's superseded runs. (session-settled: user-approved — the trigger set and concurrency cancel were proposed and affirmed.)

### Requirements

**Workflow behavior**

- R1. A workflow runs the test suite on every pull request (opened, synchronized, reopened) and on every push to `main`.
- R2. A concurrency group cancels a pull request's in-progress run when a newer commit is pushed to the same pull request.
- R3. The workflow exposes a single, stable status-check name that branch protection can require; renaming it silently breaks the gate.

**CI execution environment**

- R4. The workflow builds the application image and runs the existing container test target (`TEST_MODE`, which runs `manage.py test --exclude-tag=download astrodash.tests users.tests`) rather than re-deriving a Python environment, so CI exercises the deployed image.
- R5. Docker layer caching (GitHub Actions cache) is used so the CPU-only PyTorch install does not rebuild from scratch on every run. The test workflow's cache is scoped separately from the image-publish workflow (which already uses `type=gha`), so a pull-request build cannot populate cache layers a release build would consume.
- R6. The suite runs to completion on a GitHub-hosted runner with no repository secrets and no external data volume: the `astrodash-data` mount is satisfied by an ephemeral empty volume rather than the `external: true` volume the current `ci` Compose file declares, and data initialization is disabled with `SKIP_INITIALIZATION=true`. The empty volume alone is insufficient, because the entrypoint otherwise downloads the full data set by default (anonymous public read of the baked-in manifest, no credentials needed) — an unnecessary cost for a test-only gate that touches none of that data.
- R7. Only the test suite gates. No formatting, lint, or coverage-threshold check is added; the `coverage report` printed by `TEST_MODE` is not a gate.

**Merge gating and rollout**

- R8. A failing test run blocks merging the pull request — the check is a required status check in branch protection.
- R9. The required check is configured on both `origin/main` (skoranda) and `scimma/main` (scimma) from the same workflow file.
- R10. On each repo, the required check is enabled only after the workflow is present on that repo's `main`, so no pull request is blocked waiting on a check that can never run.
- R11. The existing tag-triggered image-publish workflow is unchanged; the test workflow is additive.

**Workflow hardening and prerequisites**

- R12. The workflow uses the `pull_request` event, never `pull_request_target`. `pull_request` is what withholds repository secrets and the write token from fork pull requests (the basis of R6 and AE4); `pull_request_target` would run fork changes with secrets and a write token in the base-repo context and must not be used.
- R13. The workflow declares an explicit least-privilege `permissions:` block (`contents: read`, nothing more), so its token scope does not depend on either repository's default token setting.
- R14. Untrusted pull-request context (title, branch, `head_ref`, labels) is never interpolated directly into `run:` shell; when such a value is needed it is passed through `env:` and referenced as a shell variable. Using `github.head_ref` in the concurrency-group key is safe, since that is not a shell context.
- R15. The CI job stands up the `database` service so the entrypoint's pre-test steps (migrations, static-file collection, superuser setup) complete before the suite runs; database availability is a prerequisite of the gate, not incidental.

### Acceptance Examples

- AE1. **Covers R1.** **Given** an open pull request, **when** a new commit is pushed to it, **then** the test workflow runs automatically against that commit.
- AE2. **Covers R1.** **Given** a pull request is merged, **when** the merge lands on `main`, **then** the test workflow runs on `main`.
- AE3. **Covers R8.** **Given** a pull request whose test run fails, **when** a merge is attempted, **then** it is blocked until a run passes.
- AE4. **Covers R6, R12.** **Given** a pull request opened from a fork (where GitHub withholds secrets), **when** the workflow runs, **then** the suite completes and reports pass/fail, because it needs no secrets or external data.
- AE5. **Covers R2.** **Given** two commits pushed to the same pull request in quick succession, **when** the second run starts, **then** the first is cancelled and only the latest runs to completion.

### Success Criteria

- A red suite blocks the merge on both repos; every pull request and every merge to `main` triggers a run; CI runs the same image that deploys; and a fork pull request with no secrets still completes the suite.

### Scope Boundaries

**Deferred for later:**

- A `black --check` / lint gate and a coverage floor or Codecov upload.
- Gating the `download`-tagged, data-dependent tests (would require model data or credentials in CI).
- Self-hosted runners and a multi-version test matrix.

**Outside this work's identity:**

- The DEV/PROD rollout of the open model-registry pull request — a separate track.
- The image build-and-push workflow (`docker_image_workflow.yml`) — untouched; deploy automation is not in scope.

### Outstanding Questions

**Deferred to planning:**

- The exact mechanism for the ephemeral `astrodash-data` volume in CI (a CI-only Compose override, dropping `external: true`, or binding an empty directory) and where `SKIP_INITIALIZATION=true` is set — a CI-only Compose override versus `env/.env.ci`, which currently sets only `FORCE_INITIALIZATION=true` while `env/.env.default` sets `SKIP_INITIALIZATION=false`.
- The exact stable check-name string, and the specific caching approach (`docker/build-push-action` with `cache-from/to: type=gha`, or a `buildx` cache) — with a cache key or scope distinct from `docker_image_workflow.yml`'s `type=gha` cache, per R5.
- Whether to upload `coverage.xml` as a non-gating artifact.

**Recorded, not blocking:**

- Branch protection is a repository Settings change the maintainer performs; the plan documents the steps for both repos but cannot apply them in code.

### Sources / Research

- `.github/workflows/docker_image_workflow.yml` — the only existing workflow; triggers on version tags, builds/pushes the image. No PR or test trigger.
- `app/entrypoints/docker-entrypoint.app.sh` — the `TEST_MODE=1` branch runs `coverage run manage.py test --exclude-tag=download astrodash.tests users.tests` then `coverage report`/`coverage xml`; `SKIP_INITIALIZATION` short-circuits data init.
- `app/entrypoints/initialize_data.py` — data init reads from S3 and only downloads when credentials are present, so it no-ops without them.
- `docker/docker-compose.ci.yaml` — the `ci` profile (`app` + `database`, `TEST_MODE=1`); declares `astrodash-data` as `external: true`.
- `docker/docker-compose.yml` — the `app` service mounts `astrodash-data:/mnt/astrodash-data` and includes the `ci` profile.
- `run/get_compose_args.sh`, `run/astrodashctl` — the `ci` profile wiring (`--exit-code-from`, project `astrodash-ci`).
- Git remotes — `origin` = `skoranda/astrodash` (fork), `upstream` = `scimma/astrodash` (canonical); pull requests target upstream.

---

## Planning Contract

**Product Contract preservation:** unchanged. Planning adds HOW (the override file, the workflow shape, the runbook) and resolves the deferred Outstanding Questions into KTDs; no requirement, acceptance example, or scope boundary was rewritten. External research was not run — the repo's own `docker_image_workflow.yml` establishes the action stack to mirror.

### Key Technical Decisions

- KTD1. **CI environment via a dedicated GitHub-CI Compose override, not edits to shared config.** A new `docker/docker-compose.ci.github.yaml` is layered after `docker-compose.ci.yaml`: it redeclares the `astrodash-data` volume with an explicit `external: false` (Compose merges top-level volumes by key and keeps base keys an override omits, so the flag must be set explicitly, not merely left out) and sets `SKIP_INITIALIZATION=true` on the `app` service. (session-settled: user-approved — chosen over editing `env/.env.ci` or `docker-compose.ci.yaml` directly: keeps the shared `ci` profile and any self-hosted use with the real data volume untouched. Implements R6 and R15.)
- KTD2. **The workflow invokes `docker compose` directly and builds with an isolated cache scope.** It mirrors `docker_image_workflow.yml`'s action stack (`jlumbroso/free-disk-space`, `actions/checkout@v6`, `docker/setup-buildx-action@v4`, `docker/build-push-action@v7`) but builds with `load: true` (not push) and `cache-from`/`cache-to: type=gha,scope=ci-test` — a scope distinct from the publish workflow's default `type=gha` — then runs the two-file `ci` stack with `up --exit-code-from app`. (Implements R4, R5, R12. Sidesteps the `run/get_compose_args.sh` `app_ci` naming wart, deferred below.)
- KTD3. **Required gate, container-parity, both repos, tests-only, `pull_request`-not-`pull_request_target`** — inherited from the Product Contract Key Decisions. (session-settled: user-directed — see the Product Contract's Key Decisions and R8-R13; the plan mechanizes them without re-deciding.)
- KTD4. **Branch protection is documented, not automated.** A runbook gives the exact required-check name and the both-repos plus enable-after-workflow-on-`main` steps; the Settings toggle itself is the maintainer's action. (Implements R8-R10.)
- KTD5. **Concurrency cancels PR runs only (keyed on `github.head_ref`), and the workflow declares `permissions: contents: read`.** Main-branch pushes are not cancelled; `head_ref` in the concurrency key is safe because it is not a shell context. (Implements R2, R13, R14.)

### Assumptions

- The suite passes under the `ci` profile env (`env/.env.default` + `env/.env.ci`); Django's settings read the `SECRET_KEY` env var, which has a hardcoded insecure default, so the empty `DJANGO_SECRET_KEY` in `.env.default` does not affect it. The local two-file compose run in the Verification Contract confirms the suite before the workflow is trusted.
- `docker compose up` on the two `ci` files brings up both `app` and `database`; `TEST_MODE=1` (set in `docker-compose.ci.yaml`) makes `app` run the suite via the entrypoint and exit with the test exit code, which `--exit-code-from app` surfaces.

### Risks & Dependencies

- The workflow file must be present on a repo's `main` before that repo's required check is enabled (R10), or open PRs block on a check that never runs.
- **Deferred follow-up (pre-existing, out of scope):** `run/get_compose_args.sh` sets `TARGET_SERVICE=app_ci` and `--exit-code-from app_ci`, while `docker-compose.ci.yaml` names the service `app` and `run/astrodashctl` uses `--exit-code-from app`. The workflow avoids this by calling `docker compose` directly with `--exit-code-from app`; reconciling the two runner scripts is a separate cleanup.
- `coverage.xml` (produced inside the container by `TEST_MODE`) is not uploaded — tests-only per the settled decision. Adding an `actions/upload-artifact` step later is a low-cost follow-up.
- With `external: false` the override keeps the literal volume name `astrodash-data` (not project-prefixed). Harmless on ephemeral GitHub-hosted runners (always fresh), but a self-hosted persistent runner would reuse the same-named local volume across runs — acceptable for the GitHub-hosted scope of this plan.

---

## Output Structure

```text
.github/workflows/test.yml            # the test-gate workflow (new)
docker/docker-compose.ci.github.yaml  # CI-only override: ephemeral data volume + SKIP_INITIALIZATION=true (new)
docs/admin/ci-required-check.md       # branch-protection runbook for both repos (new)
```

The per-unit `**Files:**` sections remain authoritative; the runbook path follows wherever admin/operator docs live in `docs/`.

---

## Implementation Units

### U1. CI-only Compose override

- **Goal:** Give the `ci` profile a GitHub-hosted-runner variant that needs no external data volume and skips data initialization.
- **Requirements:** R6, R15 (KTD1).
- **Dependencies:** none.
- **Files:** `docker/docker-compose.ci.github.yaml` (new).
- **Approach:** A minimal Compose override applied after `docker/docker-compose.ci.yaml`. Redeclare the `astrodash-data` volume with an explicit `external: false` so a fresh empty volume is created each run — an empty `{}` override would keep the base's `external: true` (Compose merges volume keys and retains what the override omits) and fail with "external volume not found" on a hosted runner. Set `SKIP_INITIALIZATION=true` on the `app` service environment (a service `environment:` value overrides `.env.default`'s `SKIP_INITIALIZATION=false`) so the entrypoint skips `initialize_data.py` and its anonymous S3 downloads. (`.env.ci` also carries `FORCE_INITIALIZATION=true`, which only clears a stale lock file and does not re-enable init when `SKIP_INITIALIZATION=true`.) Do not change the ci services otherwise — `database` and the `app` `TEST_MODE` target come from the base ci file.
- **Execution note:** Mostly config; smoke-verify by running the two-file compose stack locally (see Verification Contract), not by unit tests.
- **Patterns to follow:** `docker/docker-compose.ci.yaml` and `docker/docker-compose.dev.yaml` (this repo's compose override/`extends` style).
- **Test scenarios:** Test expectation: none — Compose configuration. Behavioral proof is the local run in the Verification Contract: the suite runs to completion, the logs show no S3 download attempts against the empty volume, and the run exits 0 on green.
- **Verification:** build the image once (`docker build -f app/Dockerfile -t astrodash:latest ./app`; the ci `app` service uses `image:`, not `build:`), then `docker compose --profile ci -f docker/docker-compose.ci.yaml -f docker/docker-compose.ci.github.yaml --env-file env/.env.default --env-file env/.env.ci up --exit-code-from app` runs the suite green with no data-download log lines and exits 0. `--profile ci` is required — the base `app`/`database` services are profile-gated (inherited via `extends`), so omitting it starts no services.

### U2. The test-gate workflow

- **Goal:** The GitHub Actions workflow that runs the suite as a check on pull requests and on merges to `main`.
- **Requirements:** R1, R2, R3, R4, R5, R7, R11, R12, R13, R14 (KTD2, KTD3, KTD5).
- **Dependencies:** U1.
- **Files:** `.github/workflows/test.yml` (new).
- **Approach:**
  - Triggers: `pull_request` with `types: [opened, synchronize, reopened]`, and `push: { branches: [main] }`. Never `pull_request_target` (R12).
  - Top-level `permissions: contents: read` (R13).
  - `concurrency`: group keyed on the workflow plus `github.head_ref || github.ref`, with `cancel-in-progress` true only for `pull_request` events so `main` pushes are never cancelled (R2, R14).
  - One job, `runs-on: ubuntu-latest`, with a **stable pinned name** that becomes the required-check identifier (R3) — do not rename it later.
  - Steps mirror `docker_image_workflow.yml`: `jlumbroso/free-disk-space` (the CPU-torch image is large), `actions/checkout@v6`, `docker/setup-buildx-action@v4`, then `docker/build-push-action@v7` with `context: ./app`, `file: ./app/Dockerfile`, `load: true` (not `push`), `tags: astrodash:latest` (the tag the compose expects), and `cache-from`/`cache-to: type=gha,scope=ci-test` distinct from the publish workflow's default scope (R5).
  - Run the suite: `docker compose --profile ci -f docker/docker-compose.ci.yaml -f docker/docker-compose.ci.github.yaml --env-file env/.env.default --env-file env/.env.ci up --abort-on-container-exit --exit-code-from app`; a nonzero test exit fails the job. The `--profile ci` selector is required — the base `app`/`database` services are gated behind the `ci` profile (inherited via `extends`), so omitting it starts no services.
  - Do not interpolate untrusted PR context (title, branch, labels) into any `run:` shell (R14).
- **Execution note:** Config/YAML; validate syntax (`actionlint` if available, else a YAML parse / `gh workflow`), and rely on U1's local compose smoke run for behavioral proof. True end-to-end proof is the first PR run once the file is on a branch pushed to `origin`.
- **Patterns to follow:** `.github/workflows/docker_image_workflow.yml` (same action versions and buildx/cache shape).
- **Test scenarios:** Test expectation: none — CI configuration. Covers AE1 (runs on PR events and `push: main`), AE2 (runs on merge to `main`), AE4 (a fork PR uses the `pull_request` event, gets no secrets, and still runs), and AE5 (concurrency cancels a superseded PR run) — verified by observing the workflow on a real PR/push, not by unit tests.
- **Verification:** the workflow parses/lints and shows the triggers, `permissions: contents: read`, concurrency, and pinned job name, with no `pull_request_target`; on a PR to `origin` it triggers and runs the suite to green; a second push to the same PR cancels the prior run; the run consumes no secrets.

### U3. Branch-protection runbook

- **Goal:** Document the required-check setup on both repos so the gate is actually binding.
- **Requirements:** R8, R9, R10 (KTD4).
- **Dependencies:** U2 (the check name must exist first).
- **Files:** `docs/admin/ci-required-check.md` (new; place under the repo's admin/operator docs area).
- **Approach:** A short operator runbook giving the exact status-check name to require (the U2 job name), the steps to add it as a required status check in branch protection on `origin/main` (skoranda) and `scimma/main` (scimma), and the ordering rule — enable the required check on a repo only after the workflow file is on that repo's `main`, or PRs block on a check that never runs (R10). Note that fork PRs run with no secrets (safe) because the workflow is `pull_request`-based.
- **Execution note:** Documentation only. Test expectation: none — documentation.
- **Test scenarios:** Covers AE3 (a failing run blocks the merge) — satisfied once the runbook-directed required status check is enabled on each repo; this is a maintainer Settings action, not code-verifiable. Otherwise none (documentation).
- **Verification:** the runbook names the correct check and the both-repos plus ordering steps; a maintainer can enable the gate from it without further research.

---

## Verification Contract

- **Local behavioral proof (the gate before trusting CI):** build the image (`docker build -f app/Dockerfile -t astrodash:latest ./app`), then `docker compose --profile ci -f docker/docker-compose.ci.yaml -f docker/docker-compose.ci.github.yaml --env-file env/.env.default --env-file env/.env.ci up --exit-code-from app` — the suite runs to completion, the logs show no data-download attempts (SKIP_INITIALIZATION honored) against the empty ephemeral volume, and the command exits 0 on green (nonzero when a test is deliberately failed). `--profile ci` is mandatory: the ci services are profile-gated, so omitting it starts nothing.
- **Workflow validation:** the YAML parses (`actionlint` if available, else a YAML parse / `gh workflow view`); triggers, `permissions: contents: read`, concurrency, and the pinned job name are present, and `pull_request_target` does not appear.
- **End-to-end (after the file is on a branch pushed to `origin`):** opening a pull request triggers the workflow and the check reports; a superseded PR run is cancelled; the run consumes no secrets.
- **Regression:** `docker_image_workflow.yml` is unchanged, and no shared `ci` config (`env/.env.ci`, `docker/docker-compose.ci.yaml`) is mutated.

---

## Definition of Done

- R1-R15 satisfied.
- `.github/workflows/test.yml` runs the suite on `pull_request` (opened/synchronize/reopened) and `push: main`, never `pull_request_target`; declares `permissions: contents: read`; cancels superseded PR runs via a concurrency group keyed on `head_ref` (not shell-interpolated); and has a stable pinned job name serving as the required-check identifier.
- The workflow builds the app image (`build-push-action`, `load: true`, `type=gha` cache scoped `ci-test` and isolated from the publish workflow) and runs the suite through `docker-compose.ci.yaml` + `docker-compose.ci.github.yaml`; the local two-file compose run is green, with the database up and no S3 download attempts.
- `docs/admin/ci-required-check.md` documents enabling the required check on both `origin/main` and `scimma/main`, including the enable-after-workflow-on-`main` ordering.
- `docker_image_workflow.yml` is untouched; no shared `ci` profile config is mutated. The `get_compose_args.sh`/`app_ci` naming inconsistency is recorded as a follow-up, not fixed here.
- Changed YAML/Compose is validated and the runbook is accurate.
