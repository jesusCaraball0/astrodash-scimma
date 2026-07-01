---
date: 2026-07-01
topic: local-dev-app-version
---

# Local-Dev APP_VERSION from git describe

## Summary

Extend the APP_VERSION source-of-truth mechanism to the local docker-compose dev flow. On the `full_dev` and `slim_dev` profiles, `run/astrodashctl` computes `git describe --tags --always` on the host and exports it, and `docker/docker-compose.dev.yaml` reads it into the app container's `APP_VERSION` env var. The footer, `/healthz`, and startup log all show the git-describe string instead of the `local` placeholder. Non-dev profiles and raw `docker compose up` outside `astrodashctl` continue to fall back to `local`.

## Problem Frame

The 2026-06-25 brainstorm (`docs/brainstorms/2026-06-25-version-source-of-truth-requirements.md`) landed on a deliberate `local` placeholder for any environment without `APP_VERSION` set. In production that value never appears — the Helm chart always sets `APP_VERSION` from `.Values.image.tag`. But local docker-compose is the second most common runtime shape for this app, and there the footer always reads `local`.

When a developer runs multiple checkouts, worktrees, or branches through the same docker-compose stack — routine here, especially with `.worktrees/feat-<x>` alongside `main` — the footer is silent about which one is loaded. The developer can still verify code identity by inspecting the container or the mounted `app/` directory, but the fastest signal (the footer, designed to report what's running) carries no information.

The plumbing to fix this already exists. `run/astrodashctl` is the canonical bash launcher and already exports env vars before invoking `docker compose`. `docker/docker-compose.dev.yaml`'s app service already has an `environment:` block. `settings.APP_VERSION` already reads the env var. The missing link is astrodashctl computing `git describe` on the host and exporting it, plus one env-var entry in the compose overlay.

## Key Decisions

- **Host-side git describe, mirroring the Helm shape.** `astrodashctl` computes `git describe --tags --always` on the host at up-time and exports `APP_VERSION`; `docker-compose.dev.yaml` adds `APP_VERSION=${APP_VERSION:-local}` to the app service `environment:` block; the Django app reads `APP_VERSION` unchanged. The docker-compose flow becomes structurally symmetric with the Helm flow: external orchestrator sets env, container reads env. No new container binary (`git`), no new mount (`.git`). Container-side computation (bind-mount `.git`, install git in the dev image) is deferred; if raw `docker compose up` outside `astrodashctl` becomes a first-class launch path, revisit.

- **Snapshot at up-time, not live per request.** The value is fixed by whatever `git describe` returned when `astrodashctl full_dev up` was invoked; `docker compose restart app` alone doesn't re-interpolate. The `--dirty` flag is intentionally omitted from the git describe invocation because the dev overlay bind-mounts `../app:/app`: running code diverges from the snapshotted working-tree state the moment anyone edits after `up`, and a stale `-dirty` (or worse, a stale non-dirty) suffix would report false state with authoritative styling. Commit-level staleness — a new commit after `up` doesn't refresh the footer until the next `up` — is accepted, because the tag + short-commit portion still discriminates worktrees, which is what the Problem Frame actually needs.

- **Dev profiles only.** `full_dev` and `slim_dev` get the git-describe treatment. `full_prod`, `slim_prod`, `ci`, and `docs` keep the `local` placeholder — prod compose profiles are local prod simulation with a different intent, and CI runs often have shallow or detached checkouts that would produce noisy `--dirty` or short-hash output.

- **Display the git-describe string verbatim.** No parsing, no synthesis, no stripping of the abbreviated-commit tail. The footer renders the raw string; the release-link target is `.../releases/tag/<the-same-string>`. That link 404s by design when the string isn't a real release tag, matching the "clearly not a release" affordance the 2026-06-25 brainstorm established for the `local` placeholder in its AE3.

- **No Django source changes.** `resolve_app_version()` in `app/astrodash_project/settings.py`, the `app_version` template tag, `get_health_status()`, and `AstroDashConfig.ready()` already read `settings.APP_VERSION`. A git-describe string flows through the existing pipeline unchanged.

## Requirements

### astrodashctl (host-side)

- R1. `run/astrodashctl`, when invoked with `full_dev` or `slim_dev`, computes `git describe --tags --always 2>/dev/null || echo local` and exports the result as `APP_VERSION` before invoking `docker compose ... up`. The computation runs after profile switching but before the compose invocation.
- R2. A pre-existing `APP_VERSION` in the invoker's environment is preserved. `astrodashctl` only computes and exports when `APP_VERSION` is unset or empty, so `APP_VERSION=foo run/astrodashctl full_dev up` renders `foo` in the footer.
- R3. Non-dev profiles (`full_prod`, `slim_prod`, `ci`, `docs`) do not compute or export `APP_VERSION`. Whatever the invoker's environment holds (typically nothing) propagates untouched.

### docker-compose

- R4. `docker/docker-compose.dev.yaml`'s app service `environment:` block includes `APP_VERSION=${APP_VERSION:-local}` — passing whatever `astrodashctl` (or the invoker) has in the host environment through to the container, with `local` as the compose-default fallback for launches that bypass `astrodashctl`.
- R5. No other compose file (`docker-compose.yml`, `docker-compose.prod.yaml`, `docker-compose.ci.yaml`) is modified. Non-dev-profile app containers see whatever `APP_VERSION` is in the invoking environment (typically nothing), and `settings.APP_VERSION` falls back to `local` unchanged.

## Acceptance Examples

- AE1. **Covers R1, R4.** **Given** a developer runs `run/astrodashctl full_dev up` from a checkout where `git describe --tags --always` returns `dev2-v1.1.0-3-gabc1234`, **when** they load any page served by the dev stack, **then** the footer shows `// dev2-v1.1.0-3-gabc1234` and the release link target is `https://github.com/scimma/astrodash/releases/tag/dev2-v1.1.0-3-gabc1234` (a 404, consistent with AE3 of the 2026-06-25 brainstorm).
- AE2. **Covers R2.** **Given** a developer runs `APP_VERSION=custom-value run/astrodashctl full_dev up`, **when** they load the footer, **then** the displayed value is `custom-value` — the pre-existing env var is preserved and passes through to the app container.
- AE3. **Covers R1, R4.** **Given** a developer runs `run/astrodashctl full_dev up` from a checkout where `git describe --tags --always` fails (no tags reachable and `--always` also fails, e.g. a broken `.git`), **when** they load the footer, **then** the displayed value is `local` — astrodashctl's `|| echo local` fallback fires.
- AE4. **Covers R3, R5.** **Given** a developer runs `run/astrodashctl full_prod up` (local prod simulation) or `run/astrodashctl ci up`, **when** the app container starts, **then** the footer shows `local`. `astrodashctl` doesn't compute `git describe` for these profiles, and their compose overlays don't define `APP_VERSION`, so `settings.APP_VERSION` falls back to `local` in the Django layer.
- AE5. **Covers R4.** **Given** a developer runs `docker compose --file docker/docker-compose.yml --file docker/docker-compose.dev.yaml --profile full_dev up` directly (bypassing `astrodashctl`) with no pre-set `APP_VERSION` in the invoking environment, **when** the app container starts, **then** the footer shows `local` — the compose file's `${APP_VERSION:-local}` default fires.

## Scope Boundaries

- **Container-side computation (Approach B) is deferred.** Bind-mounting `.git` and installing `git` in the dev image would let raw `docker compose up` outside `astrodashctl` still get a meaningful footer, but the trade-off (image dep, `.git` mount, more moving parts) isn't worth it while `astrodashctl` is the canonical launcher.
- **`full_prod`, `slim_prod`, `ci`, and `docs` profiles keep the `local` placeholder.** Different intent (local prod simulation is not the developer's own code being served); CI checkouts are commonly shallow or detached and would produce noisy output.
- **Refreshing the footer without a full down/up cycle is out of scope.** A developer who commits new code after `astrodashctl full_dev up` sees the old value in the footer until they re-run `astrodashctl full_dev up` (which re-renders compose and picks up the new host env). `docker compose restart app` alone does not re-render.
- **The release-link footer target is unchanged.** Still points at `releases/tag/<APP_VERSION>` — a 404 for git-describe values, matching today's 404 for `local`. Not a bug this brainstorm is fixing.
- **Tag-naming and `git describe` flag variations are not in scope.** The combo `--tags --always` is the default; alternate shapes (`--long`, `--first-parent`, custom `--match` filters) are not explored.
- **Helm/Kubernetes deploy path is unchanged.** The Helm chart still passes `.Values.image.tag` unchanged. This brainstorm is a parallel dev-side mechanism, not a change to the deploy path.

## Dependencies / Assumptions

- The host running `astrodashctl` has `git` installed and can `git describe` from the repo working directory. `run/astrodashctl:5` `cd`s to the repo root, so the working directory context is correct. If `git` is unavailable or fails, the `|| echo local` fallback fires.
- `docker compose ... up` interpolates compose files at up-time using the host environment; a value exported before the invocation is picked up by `${APP_VERSION:-local}` in the YAML. `docker compose restart <svc>` does not re-interpolate — refresh requires a full `down` + `up` cycle (or another `up` invocation — compose recreates the service if the env changed).
- The bind-mounted `app/` directory (`../app:/app` in `docker-compose.dev.yaml:45`) does not include the host's `.git` — that's above the mount. Container-side git commands cannot see the repo without an additional mount, which Approach B would require and this brainstorm defers.
- `settings.APP_VERSION` still uses the `or "local"` fallback from the 2026-06-25 brainstorm's R1, so any path where the env var doesn't reach the container renders `local` rather than blank or crashing.
- The existing R5 grep guard (`app/astrodash/tests/test_no_version_literals.py`) scans `.py` files only. YAML and bash changes don't reach the scan; the compose default `local` is not a semver shape and would not trigger even if scanned.

## Outstanding Questions

- Whether a bash smoke test or shellcheck coverage for the astrodashctl change is worth adding — planning decides. The existing Django test suite still passes unchanged.
- Whether to add a short mention in `docs/` (or a README/runbook entry) pointing developers at the git-describe behavior, or whether the startup log line already emitted by `AstroDashConfig.ready()` is sufficient discovery.

## Sources

- `docs/brainstorms/2026-06-25-version-source-of-truth-requirements.md` — the parent brainstorm this one extends; particularly R1 (the `local` fallback contract) and AE3 (the 404 signal).
- `app/astrodash_project/settings.py:16` — `resolve_app_version()`, unchanged by this brainstorm.
- `docker/docker-compose.dev.yaml:36-42` — app service `environment:` and `env_file:` blocks; the insertion point for R4.
- `run/astrodashctl:5,16-48,69-76` — `cd` to repo root, profile switching, and the `docker compose up` invocation site; the insertion point for R1–R3.
- `env/.env.default`, `env/.env.dev` — env files loaded into the container; documented for completeness, not modified.
