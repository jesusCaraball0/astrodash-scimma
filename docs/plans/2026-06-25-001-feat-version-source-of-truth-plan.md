---
title: "feat: Wire APP_VERSION to deployed image tag"
type: feat
date: 2026-06-25
origin: docs/brainstorms/2026-06-25-version-source-of-truth-requirements.md
---

# feat: Wire APP_VERSION to deployed image tag

## Summary

Make `settings.APP_VERSION` read an `APP_VERSION` environment variable set by the Helm chart directly from `.Values.image.tag`, with a `local` fallback when unset, and collapse the four hardcoded version sites (settings constant, template tag, footer link, dormant `/healthz` payload) onto that one constant. Display the chart tag verbatim; link the footer to a GitHub release at that exact tag.

## Problem Frame

Tagging a release in git no longer produces a coherent change in what the deployed app says about itself. `APP_VERSION` lives as a string literal in `app/astrodash_project/settings.py:15` and is duplicated in three other surfaces. The deploy pipeline already produces a per-environment image tag (`dev2-v1.1.0`, `v1.0.0`); the missing link is propagating that tag into the running pod's environment. See origin: `docs/brainstorms/2026-06-25-version-source-of-truth-requirements.md`.

---

## Requirements

### Django app (`astrodash` repo)

- R1. `app/astrodash_project/settings.py` reads `APP_VERSION` from the environment, falling back to the literal string `local` when the env var is unset or empty.
- R2. The `app_version` template tag (`app/astrodash/templatetags/astrodash_tags.py`) returns `settings.APP_VERSION` verbatim — no `v` or other prefix.
- R3. The footer template (`app/astrodash/templates/astrodash/base_site.html`) renders `settings.APP_VERSION` as the displayed text AND as the path component in the GitHub release link, so the link target is `https://github.com/scimma/astrodash/releases/tag/<APP_VERSION>`.
- R4. `get_health_status()` in `app/astrodash/core/monitoring.py` reads `settings.APP_VERSION` instead of holding its own literal.
- R5. No production source file under `app/` holds a hard-coded version literal. An automated check (see U2) fails the test suite if a `__version__` assignment or bare-semver literal appears in production source files outside `app/astrodash/tests/`, excluding auto-generated migration files and compiled artifacts.
- R6. The Django app emits a single INFO-level log line at startup announcing the active `APP_VERSION`, so operators can confirm what's running from pod logs.

### Helm chart (`astrodash-k8s-gitops` repo)

- R7. The web container in `apps/astrodash/templates/deployment-app.yaml` sets `APP_VERSION` as an environment variable whose value is templated directly from `.Values.image.tag`.
- R8. No additional `.Values.config` key is added — `APP_VERSION` is derived from `image.tag` at template time, not stored as a parallel value.

---

## Key Technical Decisions

- **Inline `env:` on the web container, not the ConfigMap range.** The existing ConfigMap template iterates `.Values.config` (`apps/astrodash/templates/configmap.yaml`), and R8 precludes adding an `APP_VERSION` key there. Mixing range-driven entries with one explicit literal in the ConfigMap would obscure the pattern. An inline `env:` block on just the web container is the standard Kubernetes shape for one-off values not coming from a ConfigMap or Secret, and keeps the truth-source (`.Values.image.tag`) visible at the point of consumption.
- **`local` placeholder pinned during brainstorm review.** Non-semver-shaped on purpose, so a deploy that accidentally ships without the env var set cannot impersonate a real release in the footer. Resolved in the requirements doc; carried forward without revisiting.
- **Test-first execution for U1.** The acceptance examples in the origin doc give every test its inputs and expected outcomes; failing tests anchor the implementation without forcing the implementer to invent coverage.
- **Pytest grep guard over CI lint for R5.** Pytest already gates merges; adding the regression check there keeps the enforcement co-located with the rest of the test suite and avoids new CI configuration in either repo.
- **`AppConfig.ready()` for the startup log line.** Django's standard one-time-at-start hook; mirrors the existing `TwinsSearchService loaded` INFO pattern in `app/astrodash/domain/services/twins_search_service.py`.

---

## Implementation Units

### U1. Django: env-var-driven `APP_VERSION` and consolidated version sites

**Goal:** `settings.APP_VERSION` reads the env var with `local` fallback; the template tag, footer, and `/healthz` payload all derive from that constant.

**Requirements:** R1, R2, R3, R4.

**Dependencies:** none.

**Files:**
- `app/astrodash_project/settings.py` (modify the `APP_VERSION` line)
- `app/astrodash/templatetags/astrodash_tags.py` (drop the `prefix` argument and return value verbatim)
- `app/astrodash/templates/astrodash/base_site.html` (footer block at line 189 — render and link to the same value)
- `app/astrodash/core/monitoring.py` (line 75 — read `settings.APP_VERSION`)
- `app/astrodash/tests/test_settings_app_version.py` (new — settings env-var behavior)
- `app/astrodash/tests/test_app_version_template_tag.py` (new — template tag rendering)

**Approach:** `settings.APP_VERSION = os.environ.get("APP_VERSION") or "local"` — using `or` rather than the second positional argument so an explicit empty string also falls back. The template tag becomes a zero-argument `simple_tag` returning `settings.APP_VERSION`; the base template invocation becomes `{% app_version %}` for both the link text and the path component in the `href`. `monitoring.py` imports `settings` (the `django.conf.settings` lazy proxy already used elsewhere in the file) and reads `settings.APP_VERSION` in the `health_status` dict.

**Execution note:** Start with failing tests for the settings env-var behavior and the template tag. Implement settings + template tag + monitoring change in one pass; touch the template last.

**Patterns to follow:** `SECRET_KEY` and `DJANGO_DEBUG` reads at `app/astrodash_project/settings.py:23-28` — same `os.environ.get` shape with default fallback.

**Test scenarios:**
- **Covers AE1.** `APP_VERSION=dev2-v1.1.0` in the environment → `settings.APP_VERSION == "dev2-v1.1.0"`; the rendered footer text is `dev2-v1.1.0` and the link target ends with `/releases/tag/dev2-v1.1.0`.
- **Covers AE2.** `APP_VERSION=v1.0.0` in the environment → same shape, value is `v1.0.0` end-to-end.
- **Covers AE3.** `APP_VERSION` unset → `settings.APP_VERSION == "local"`; footer text is `local`; link target is `/releases/tag/local`.
- `APP_VERSION=""` (empty string) → `settings.APP_VERSION == "local"` (empty treated as unset per R1).
- **Covers AE4.** `get_health_status()` returns a dict whose `version` field equals `settings.APP_VERSION` regardless of value.
- The template tag, invoked as `{% app_version %}` with no positional argument, returns the bare value with no leading `v` or other prefix.

**Verification:** New pytest tests pass; existing test suite still green. Manual: set `APP_VERSION=manual-check` in the local dev shell and confirm the footer shows `manual-check` linking to `releases/tag/manual-check`.

### U2. R5 regression guard: pytest check for stray version literals

**Goal:** Fail the test suite if any production source file under `app/` reintroduces a version literal.

**Requirements:** R5.

**Dependencies:** U1 (the guard runs against the post-U1 codebase).

**Files:**
- `app/astrodash/tests/test_no_version_literals.py` (new)

**Approach:** A single pytest test walks `app/` (excluding `app/astrodash/tests/`, `__pycache__`, and any `migrations/` directories) and scans each `.py` file for two patterns: (a) any `__version__\s*=` assignment, and (b) a bare three-segment semver literal like `\b\d+\.\d+\.\d+\b`, but **only on lines that also contain a case-insensitive match for `version`, `VERSION`, or `__version__`**. The keyword filter on pattern (b) is what makes the test deterministic against the existing codebase: it catches the literal `APP_VERSION = '1.0.0'`-shaped hits the requirement targets while passing over the Django docstring's `Django 3.2.9`, the `127.0.0.1` IP literal in the same file, and the sklearn/numba/umap-learn version comments in `app/astrodash/domain/services/twins_search_service.py` (none of which sit on lines containing the word `version`). The test fails with a clear list of offending paths and line numbers.

**Execution note:** none.

**Patterns to follow:** no existing regression-style tests in the suite; pattern is straightforward `pathlib.Path("app").rglob("*.py")` plus `re.search` per file.

**Test scenarios:**
- The test passes against the post-U1 codebase. Specifically, it does not flag the `Django 3.2.9` docstring in `app/astrodash_project/settings.py:4`, the `127.0.0.1` literal at `app/astrodash_project/settings.py:119`, or the sklearn/numba/umap-learn dependency comments in `app/astrodash/domain/services/twins_search_service.py:57-58, :133-134` — each of those lines lacks the `version` keyword and so is invisible to pattern (b).
- Inverse sanity (developer-only, not a committed test): inserting `APP_VERSION = '1.2.3'` or `__version__ = '1.2.3'` anywhere under `app/` outside the allowlist makes the test fail with that path surfaced.

**Verification:** `pytest app/astrodash/tests/test_no_version_literals.py` is green; the test name appears in the suite output.

### U3. Helm chart: pass `image.tag` as `APP_VERSION` on the web container

**Goal:** The deployed web container receives `APP_VERSION` set to the chart's `image.tag`.

**Requirements:** R7, R8.

**Dependencies:** U1 (the env var has no consumer until U1 ships and the new image rolls out).

**Target repo:** `astrodash-k8s-gitops`.

**Files (repo-relative within the target repo):**
- `apps/astrodash/templates/deployment-app.yaml` (modify the web container spec to add an inline `env:` block with one `APP_VERSION` entry)

**Approach:** Add an `env:` field to the web container in `deployment-app.yaml`, alongside the existing `envFrom:` (lines 82-86). The single entry is `name: APP_VERSION` / `value: {{ .Values.image.tag | quote }}`. No change to `values.yaml`, `values-dev.yaml`, or `values-prod.yaml`. The init containers do not need this env var — only the running web process renders the footer.

**Execution note:** none.

**Patterns to follow:** The existing `envFrom:` block on the web container in `apps/astrodash/templates/deployment-app.yaml:82-86`; templating `.Values.image.tag` is already done at line 71 for the container image reference, so the same value is being templated in two places consistently.

**Test scenarios:** No automated test — the gitops repo does not currently exercise `helm template` against fixtures. Manual post-deploy verification:
- `kubectl exec -n astrodash <web-pod> -- printenv APP_VERSION` returns `dev2-v1.1.0` (or whatever the values file's `image.tag` is set to).
- The dev footer at `astrodash-dev.scimma.org` shows the chart's image tag verbatim and links to `releases/tag/<that-tag>`.

**Verification:** `helm template apps/astrodash` renders without error; the rendered web Deployment shows the `env:` entry on the web container only (not on init containers).

### U4. Operator visibility: log active `APP_VERSION` at startup

**Goal:** A single INFO log line at Django app startup names the active `APP_VERSION` so operators can confirm what's running from pod logs.

**Requirements:** R6.

**Dependencies:** U1.

**Files:**
- `app/astrodash/apps.py` (add a `ready()` method to `AstroDashConfig`)

**Approach:** `AstroDashConfig.ready()` calls `get_logger(__name__).info("AstroDash starting with APP_VERSION=%s", settings.APP_VERSION)`. The Django docs note `ready()` may run more than once in some test setups; the log line is idempotent and the duplication is acceptable.

**Execution note:** none.

**Patterns to follow:** `TwinsSearchService loaded: N=%d, dim=%d` INFO line at `app/astrodash/domain/services/twins_search_service.py:86` — same logger source (`astrodash.config.logging.get_logger(__name__)`) and same INFO-level shape.

**Test scenarios:** Optional — none required for behavior the operator visually confirms in pod logs. If a test is added, it constructs the AppConfig and asserts an INFO log record matching the expected message is emitted; skip if the existing test scaffolding doesn't readily exercise app readiness.

**Verification:** After local dev startup or pod start, the gunicorn log contains a single line of the form `AstroDash starting with APP_VERSION=<value>` at INFO level.

---

## Scope Boundaries

### Deferred to follow-up work

- None — every brainstorm requirement is covered by U1–U4.

### Deferred for later (from origin)

- Approach B (build-baking the version into the image via a Dockerfile `ARG`) and Approach C (chart-side override on top of a baked-in default). Both are layerable on top of Approach A if a future need surfaces.
- Automation that edits chart `image.tag` for you (ArgoCD Image Updater or equivalent) — chart edits remain manual under this plan.

### Outside this product's identity (from origin)

- The current tag-naming convention (`v<semver>` for prod, `dev<N>-v<semver>` for dev) is what gets displayed; this plan does not propose normalizing it.
- Frontend styling of the footer — color, font, layout — is untouched.

---

## Acceptance Examples

Acceptance examples carry forward from the origin doc and are enforced by U1's test scenarios:

- AE1 (chart tag `dev2-v1.1.0` displayed and linked verbatim on dev) — covered by U1 settings + template tag tests.
- AE2 (chart tag `v1.0.0` displayed and linked verbatim on prod) — covered by U1 settings + template tag tests.
- AE3 (no env var → `local` displayed) — covered by U1 unset/empty-string tests.
- AE4 (`/healthz` payload's `version` equals `settings.APP_VERSION`) — covered by U1 monitoring test.

---

## Risks & Dependencies

- **Cross-repo sequencing.** U1, U2, U4 land in the `astrodash` repo. U3 lands in the `astrodash-k8s-gitops` repo and only takes effect once the new image (built from a post-U1 commit) is referenced in `values-dev.yaml` / `values-prod.yaml`. If U3 is applied before the U1-bearing image is rolled out, the chart still renders cleanly and the `APP_VERSION` env var is set on the pod — but the running image is still pre-U1 code, which continues to read its hardcoded `'1.0.0'` literal and ignores the env var entirely. Once the new image (with U1's settings change) is deployed, it picks up the now-present env var. There's no broken intermediate state because the old code remains functional until replaced.
- **`v` prefix in the chart tag.** Current chart values include the `v` (`v1.0.0`, `dev2-v1.1.0`). The template tag drops its own `v` prepend (R2), so the displayed string preserves whatever the chart says. If the team ever switches tag conventions, only the chart value changes — no Django code change.

---

## Documentation / Operational Notes

- **Local dev:** running the Django app outside the chart (no `APP_VERSION` env var) displays `local` in the footer with a release link to a non-existent `releases/tag/local` page. The 404 is the intended signal — anything other than the chart-supplied tag should not look like a real release.
- **Rollout order:** ship U1+U2+U4 in the app repo first, build and push the resulting image tag, then update the chart values file to point at the new image tag and merge the U3 chart change. ArgoCD syncs both the image swap and the chart env-var change in one reconcile.
- **Verifying a deploy:** read the gunicorn pod log for the `AstroDash starting with APP_VERSION=...` line, OR `kubectl exec` and `printenv APP_VERSION`, OR load any page and read the footer.

---

## Sources & Research

- Origin brainstorm: `docs/brainstorms/2026-06-25-version-source-of-truth-requirements.md` (round-1 doc-review-confirmed).
- Grounding dossier from the brainstorm: covers every cited file:line reference below.
  - `app/astrodash_project/settings.py:15` — current `APP_VERSION = '1.0.0'` literal.
  - `app/astrodash_project/settings.py:23-28` — `SECRET_KEY` / `DJANGO_DEBUG` env-var pattern to mirror.
  - `app/astrodash/templatetags/astrodash_tags.py:8-10` — current `app_version(prefix)` implementation.
  - `app/astrodash/templates/astrodash/base_site.html:189` — current footer rendering and release link.
  - `app/astrodash/core/monitoring.py:75` — dormant `"version": "1.0.0"` literal in `get_health_status()`.
  - `app/astrodash/domain/services/twins_search_service.py:86` — existing INFO log pattern (`get_logger(__name__).info(...)`).
  - `app/astrodash/apps.py` — existing `AstroDashConfig` to extend with `ready()`.
  - `.github/workflows/docker_image_workflow.yml:28-34` — CI tag extraction (untouched, but the upstream invariant the plan relies on).
  - `apps/astrodash/templates/deployment-app.yaml:71,82-86` (gitops repo) — web container image-tag templating and existing `envFrom:` block; the new `env:` block sits adjacent.
  - `apps/astrodash/templates/configmap.yaml` (gitops repo) — `range $key, $value := .Values.config` pattern, intentionally not used here.
  - `apps/astrodash/values-dev.yaml:3-5` and `values-prod.yaml:3-5` (gitops repo) — current `image.tag` values.
