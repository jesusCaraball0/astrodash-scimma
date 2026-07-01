---
date: 2026-07-01
type: feat
origin: docs/brainstorms/2026-07-01-local-dev-app-version-requirements.md
---

# feat: Local-dev APP_VERSION from git describe

## Summary

Extend the APP_VERSION source-of-truth mechanism to the local docker-compose dev flow. `run/astrodashctl` computes `git describe --tags --always` on the host for `full_dev` and `slim_dev` and exports it; `docker/docker-compose.dev.yaml` reads it into the app container. The footer, `/healthz`, and startup log show the git-describe string instead of the `local` placeholder. Non-dev profiles and raw `docker compose up` continue to fall back to `local`.

---

## Problem Frame

The 2026-06-25 SSoT work fixed the deployed footer via Helm but left the docker-compose dev flow reading the `local` placeholder unconditionally. When developers run multiple checkouts, worktrees, or branches through the same stack (routine here, especially `.worktrees/feat-<x>` alongside `main`), the footer carries no signal about which checkout is loaded. The plumbing to fix this already exists: `run/astrodashctl` exports env before invoking compose, `docker-compose.dev.yaml`'s app service has an `environment:` block, and `settings.APP_VERSION` already reads the env var (see origin: `docs/brainstorms/2026-07-01-local-dev-app-version-requirements.md`).

---

## Requirements Trace

| R-ID | Requirement | Unit(s) |
|---|---|---|
| R1 | `astrodashctl` computes `git describe --tags --always 2>/dev/null \|\| echo local` and exports `APP_VERSION` for `full_dev` and `slim_dev` before `docker compose ... up` | U1 |
| R2 | A pre-existing `APP_VERSION` in the invoker's environment is preserved (fallback-substitution semantics, not overwrite) | U1 |
| R3 | Non-dev profiles (`full_prod`, `slim_prod`, `ci`, `docs`) do not compute or export `APP_VERSION` | U1 |
| R4 | `docker/docker-compose.dev.yaml`'s app service `environment:` includes `APP_VERSION=${APP_VERSION:-local}` | U1 |
| R5 | No other compose file is modified | U1 (by omission) |

Acceptance examples AE1–AE5 from origin are covered by U1's verification steps below.

---

## Key Technical Decisions

- **Bundle the astrodashctl edit and the compose edit in one commit (U1).** The mechanism only works when both changes land together. Intermediate states are safe (astrodashctl exports but compose doesn't read → env reaches container but nothing changes there without R4; compose reads but astrodashctl doesn't export → footer shows `local`, same as today), so splitting would not create broken bisect states, but the single-commit shape is a clearer review unit for a mechanism change of this size.

- **Bash-native fallback substitution for R2.** Use the shell parameter-expansion form `APP_VERSION="${APP_VERSION:-$(git describe --tags --always 2>/dev/null || echo local)}"`, then `export APP_VERSION`. This preserves a pre-existing set-and-non-empty value (R2), computes lazily otherwise, and never overwrites — no `if [[ -z ... ]]` guard needed. The inner `2>/dev/null || echo local` catches every git-side failure (git binary missing, `.git` missing, no reachable commit) and produces the same sentinel `settings.py` uses.

- **Insert the astrodashctl branch after profile-switching, before compose invocation.** The natural placement is a new `case "$PROFILE"` block (or an amendment to the existing one at `run/astrodashctl:16-48`) between the existing profile switch and the `case "$ACTION"` at line 69. Compose interpolation runs at up-time and reads the shell env, so the export must complete before the `docker compose ... up` line executes.

- **Skip a bash smoke test; shellcheck-clean is the quality bar.** The astrodashctl change is ~5 lines. A dedicated bash test harness for that size is out of proportion. Instead, U3 adds a Django regression guard on the compose YAML (the more likely regression vector — someone edits the compose file and drops the line), and U1 verifies manually via footer inspection.

- **Docs mention lives in the developer docs, symmetric with the parent's operator runbook addition.** The parent brainstorm added `docs/operator-runbook.md` for the K8s deploy story. This one adds a paragraph to `docs/developer/getting-started.md` for the docker-compose dev story. Same symmetry as the mechanism itself.

---

## Implementation Units

### U1. astrodashctl exports git-describe; compose reads it

**Goal:** Make the footer track `git describe --tags --always` (or the invoker's pre-set `APP_VERSION`) whenever `astrodashctl full_dev up` or `astrodashctl slim_dev up` runs.

**Requirements:** R1, R2, R3, R4, R5. Covers origin AE1–AE5.

**Dependencies:** None. This is the mechanism unit.

**Files:**
- `run/astrodashctl` (modify)
- `docker/docker-compose.dev.yaml` (modify)

**Approach:**

1. In `run/astrodashctl`, after the profile-switching `case "$PROFILE"` block (currently ends around line 48) and before the compose invocation `case "$ACTION"` block (currently starts around line 69), insert a per-profile branch:
   - For `full_dev` and `slim_dev`: run `APP_VERSION="${APP_VERSION:-$(git describe --tags --always 2>/dev/null || echo local)}"` then `export APP_VERSION`.
   - For all other profiles: no-op (leave `APP_VERSION` untouched — R3).
2. In `docker/docker-compose.dev.yaml`, add `- "APP_VERSION=${APP_VERSION:-local}"` to the app service's `environment:` block (currently lines 36–39, the block already contains `DEV_MODE`, `ASTRO_DASH_CORS_ALLOWED_ORIGINS`, `ASTRODASH_LOG_LEVEL`).
3. Do not modify `docker/docker-compose.yml`, `docker/docker-compose.prod.yaml`, or `docker/docker-compose.ci.yaml` (R5).

**Patterns to follow:**
- The existing profile-switching pattern in `run/astrodashctl:16-48` for the case-per-profile shape.
- The existing `environment:` list style in `docker/docker-compose.dev.yaml:36-39` for the YAML entry.
- The parent brainstorm's plan (`docs/plans/2026-06-25-001-feat-version-source-of-truth-plan.md`) for how the Helm chart passes `APP_VERSION` on the pod's web container — this unit is the docker-compose analog.

**Test scenarios (manual verification, matching origin AE1–AE5):**
- Covers AE1: from a clean checkout with `git describe --tags --always` returning a value like `dev2-v1.1.0-3-gabc1234`, run `run/astrodashctl full_dev up`. `curl http://localhost:4000/` (or the exposed dev URL) and confirm the footer shows `// dev2-v1.1.0-3-gabc1234` and the release link href points at `.../releases/tag/dev2-v1.1.0-3-gabc1234`.
- Covers AE2: run `APP_VERSION=custom-value run/astrodashctl full_dev up`. Confirm the footer shows `custom-value`.
- Covers AE3: run `run/astrodashctl full_dev up` in an environment where `git describe` fails (e.g. `PATH=/tmp run/astrodashctl full_dev up` to simulate git-not-found). Confirm the footer shows `local`.
- Covers AE4: run `run/astrodashctl full_prod up` (or `ci up`). Confirm the footer shows `local`.
- Covers AE5: run `docker compose --file docker/docker-compose.yml --file docker/docker-compose.dev.yaml --profile full_dev up` directly with no `APP_VERSION` in the shell env. Confirm the footer shows `local`.

**Verification:**
- Run `shellcheck run/astrodashctl` and confirm no new warnings.
- Run the existing Django test suite (`docker compose exec app python manage.py test` or the project's canonical test command) inside the container — 34/34 tests should still pass; no code paths changed.
- Perform the manual footer inspections above.

---

### U2. Developer docs mention

**Goal:** Give a developer running `astrodashctl full_dev up` a discoverable explanation of what the footer will show and how to override it.

**Requirements:** No direct R-ID — resolves origin Outstanding Question 2 (docs discovery vs. startup-log alone).

**Dependencies:** U1 (the mechanism must exist for the docs to describe it truthfully).

**Files:**
- `docs/developer/getting-started.md` (modify — add a short section)

**Approach:**

Add a short section (paragraph or two, plus a bulleted "how to override" line) explaining:
- In local dev, the footer displays the output of `git describe --tags --always` computed by `astrodashctl` at up-time.
- The value is a snapshot — new commits after `up` don't refresh the footer until the next `astrodashctl full_dev up`. `--dirty` is intentionally omitted (the dev overlay bind-mounts `../app:/app`, so the working tree diverges from the snapshot the moment code is edited; a stale `-dirty` suffix would report false state).
- Override for testing a specific string: `APP_VERSION=some-value run/astrodashctl full_dev up`.
- The value also appears in `/healthz` and the startup log line emitted by `AstroDashConfig.ready()`.

Place the section near existing content that describes the docker-compose dev flow. If `getting-started.md` has a "Running the dev stack" or similar heading, insert this as a subsection. If no obvious anchor exists, add a new heading like `### The footer version string in local dev` near the docker-compose invocation instructions.

Cross-link to `docs/operator-runbook.md` (the parent brainstorm's operator-side counterpart) so a reader sees both halves of the story.

**Patterns to follow:**
- The parent brainstorm's `docs/operator-runbook.md` addition for the K8s side — same tone, same shape.
- The existing prose voice in `docs/developer/getting-started.md`.

**Test expectation:** none — this is pure documentation; verification is a manual reading pass.

**Verification:**
- The added text renders cleanly in `docs/developer/getting-started.md` (no broken markdown).
- The explanation matches the mechanism U1 implements — no drift.

---

### U3. Django test guarding the compose YAML

**Goal:** Prevent regression on R4 — someone accidentally removes or edits the `APP_VERSION=${APP_VERSION:-local}` line in `docker/docker-compose.dev.yaml` without noticing.

**Requirements:** Regression guard on R4.

**Dependencies:** U1 (the guarded line must be present for the test to pass).

**Files:**
- `app/astrodash/tests/test_compose_app_version.py` (create)

**Approach:**

Add a `SimpleTestCase` that reads `docker/docker-compose.dev.yaml` from disk and asserts the app-service `environment:` block includes an `APP_VERSION` entry whose value is exactly `${APP_VERSION:-local}` (or the equivalent unquoted form). The assertion is a regex against the file text — no YAML parsing needed for the guard to be effective, and pattern-matching keeps the test resilient to trivial reformatting.

Path resolution: climb from the test file to the repo root via `Path(__file__).resolve().parents[N]`, then join `docker/docker-compose.dev.yaml`. Mirror the path-climbing shape used by `test_no_version_literals.py`.

Include two positive scenarios (the literal form present with `"` quotes and with `'` quotes both pass — the exact quoting isn't the point) and one negative scenario (a synthetic YAML fragment missing the line fails). The negative scenario runs against an in-memory string, not against a mutated file — the test never edits the real compose file.

**Patterns to follow:**
- `app/astrodash/tests/test_no_version_literals.py` — the existing regression guard from the parent brainstorm. This unit mirrors its shape (regex against file text, no external YAML parser dependency, both a live-filesystem scan and unit tests of the pattern itself).
- Google-style docstrings on new test methods (per user CLAUDE.md).
- Black formatting on the new file (per user CLAUDE.md).

**Test scenarios:**
- Happy path: the live `docker/docker-compose.dev.yaml` file contains a line matching `APP_VERSION=${APP_VERSION:-local}` (in either quoted form). Assertion succeeds.
- Pattern positive: an in-memory YAML fragment with `- "APP_VERSION=${APP_VERSION:-local}"` matches the guard's regex.
- Pattern positive: the same fragment with single quotes matches.
- Pattern negative: an in-memory YAML fragment with the `APP_VERSION` line removed does NOT match the guard's regex.
- Pattern negative: an in-memory YAML fragment with `APP_VERSION=` alone (missing the fallback) does NOT match.

**Verification:**
- The new test file passes when the compose YAML is correct.
- Delete the `APP_VERSION=${APP_VERSION:-local}` line from `docker/docker-compose.dev.yaml` locally, re-run the test, confirm it fails, then restore the line. (Done manually as a one-time sanity check; do not commit the deletion.)
- Run the full Django test suite; existing 34 tests plus the new tests all pass.
- Run `black app/astrodash/tests/test_compose_app_version.py` and confirm no reformatting is applied.

---

## Scope Boundaries

Carried from origin, unchanged:

- **Container-side computation (Approach B) is deferred.** Bind-mounting `.git` and installing `git` in the dev image would let raw `docker compose up` outside `astrodashctl` still get a meaningful footer; not worth the image dep and `.git` mount while `astrodashctl` is canonical.
- **`full_prod`, `slim_prod`, `ci`, and `docs` profiles keep the `local` placeholder.** Different intent; CI shallow-checkout noise.
- **Refreshing the footer without a full down/up cycle is out of scope.** `docker compose restart app` does not re-interpolate.
- **The release-link footer target is unchanged.** Still 404s for git-describe values; consistent with today's `local` behavior.
- **Tag-naming and `git describe` flag variations are not in scope.** `--tags --always` is the choice; alternate shapes not explored.
- **Helm/Kubernetes deploy path is unchanged.** Parallel dev-side mechanism.

### Deferred to Follow-Up Work

- **`env/.env.dev` var-precedence documentation.** Feasibility review flagged: if a future contributor sets `APP_VERSION` in `env/.env.dev`, astrodashctl's shell export wins during compose interpolation. Currently benign (`.env.dev` is empty), but worth a docs mention if `.env.dev` grows. Skip for now.
- **Multi-worktree AE.** Scope-guardian and adversarial noted the motivating multi-worktree scenario isn't exercised by an explicit AE. The mechanism structurally covers it, but a demonstrating AE would close the loop between Problem Frame and Acceptance Examples. Follow-up.
- **`docker compose build --build-arg APP_VERSION=...` middle path.** Adversarial noted this alternative was not enumerated. Not adopted, but worth naming and dismissing in a future doc pass.
- **Visual distinction for dev-profile footer.** Product-lens deferred question: should the dev footer visually distinguish itself from a release (color, prefix, tooltip)? Not part of this mechanism.

---

## Risks & Dependencies

- **Bash `set -e` interaction.** `run/astrodashctl` runs under `set -e` (line 3). The `git describe ... 2>/dev/null || echo local` pattern is safe under `set -e` — the OR-list succeeds via the fallback whenever git fails. Same guarantee applies inside a `$(...)` substitution. Verified in the origin's feasibility review.
- **Compose interpolation timing.** `docker compose ... up` interpolates YAML using the host environment at invocation time. `docker compose restart <svc>` does NOT re-interpolate; a new value takes effect only on the next `up`. Behavior is documented as the "snapshot at up-time" Key Decision.
- **Assumption: `git` is on the host PATH when developers run astrodashctl.** Standard developer machine assumption; the fallback covers the failure mode if the assumption breaks.

---

## Open Questions

None blocking. Both origin outstanding questions resolved:

- **Bash smoke test / shellcheck coverage** — resolved: no dedicated bash test harness; shellcheck-clean is the bar. U3 provides the meaningful regression guard on the more likely mutation vector (compose YAML edit).
- **Docs mention or startup log sufficient?** — resolved: add the docs mention (U2). The startup log alone isn't discoverable pre-launch; a developer reading getting-started.md before their first `astrodashctl full_dev up` benefits from a heads-up.

---

## Sources & Research

- `docs/brainstorms/2026-07-01-local-dev-app-version-requirements.md` — origin doc; all R-IDs and AE-IDs referenced above trace here.
- `docs/brainstorms/2026-06-25-version-source-of-truth-requirements.md` — parent brainstorm; establishes the `local` fallback contract (R1) and 404-link affordance (AE3) this plan preserves.
- `docs/plans/2026-06-25-001-feat-version-source-of-truth-plan.md` — parent plan; U3 (Helm chart env var) is the K8s analog of U1's compose-side edit here.
- `run/astrodashctl:5,16-48,69-76` — repo-root `cd`, profile switching, and `docker compose up` invocation site.
- `docker/docker-compose.dev.yaml:36-42` — app service `environment:` block; insertion point for the compose edit.
- `app/astrodash/tests/test_no_version_literals.py` — the pattern U3 mirrors (regex-against-file guard with positive/negative pattern tests).
- `app/astrodash_project/settings.py:16-33` — `resolve_app_version()`, unchanged by this plan.
- `docs/operator-runbook.md` — the operator-side counterpart from the parent work; U2 is its developer-side symmetric addition.
