---
date: 2026-06-10
topic: django-lts-upgrade-celery-removal
---

# Django LTS Upgrade and Celery Removal

## Summary

Upgrade Django from 5.1.14 to 5.2 LTS and Python from 3.11 to 3.13, and
delete the currently-unused Celery infrastructure (dependency, worker /
beat / flower services, settings block, integration files). The async
batch processing architecture decision is explicitly deferred to a
future brainstorm.

## Problem Frame

Two independent issues are best resolved in the same change window.

**Django 5.1 and Python 3.11 are both past the threshold for "currently
supported."** Django 5.1's security branch ended in December 2025; the
project is pinned at `Django==5.1.14`, which is the final 5.1 release.
The Dockerfile pins `python:3.11-slim`; CPython 3.11 has been in
security-only mode since late 2024 (regular bugfix support ended October
2024). The team's stated goal is hygiene — staying on a recent,
bugfix-supported Python — not a specific Django 6 feature.

**Celery is configured but does no work.** The project ships with the
`celery` dependency, two production services (`celery-worker`,
`celery-beat`), the `flower` monitoring UI, and the
`django-celery-results` / `django-celery-beat` Django apps. A search
across `app/` for `@shared_task`, `@app.task`, `.delay(`, and
`.apply_async(` returns zero matches outside a single comment. The
`README.md` documents batch classification as Celery-based, but the
batch processing path at `app/astrodash/views.py:388-410` runs
synchronously in the request thread via `async_to_sync`. The Celery
infrastructure is dead weight as of this commit — workers idle on an
empty queue while the work happens elsewhere.

Async batch processing is on the longer-term roadmap, but no concrete
async work is currently being designed. The right move is to take the
hygiene upgrade window to retire the misleading "we have async" surface,
without pre-committing to what async architecture comes later.

## Key Decisions

- **Django 5.2 LTS over Django 6.0.** Django 5.2 LTS supports Python
  3.10–3.13 and is supported through April 2028. The "fairly recent
  Python" want is satisfied by 3.13 on this LTS line with a single-axis
  Django change (minor version bump). Django 6.0 would force a two-axis
  upgrade (drops Python 3.10 and 3.11) and put the project on a
  non-LTS Django line for roughly twelve months — paying real migration
  cost for no additional value at the user's stated threshold.

- **Delete unused Celery infrastructure now; defer the async-architecture
  choice.** The current Celery footprint provides no behavior and
  obscures the fact that batch processing is synchronous. Removing it
  cleans up a misleading surface without pre-committing to Celery vs
  `django.tasks` (Django 6.0's background tasks framework, DEP 0014) vs
  other alternatives. The team's familiarity with Celery is preserved as
  an option for the future async work; the choice can be made against
  real requirements then. If the deferred decision lands on Celery,
  the re-introduction cost is bounded — restoring the dependency, a
  settings block, three entrypoint scripts, and the worker / beat /
  flower services in compose. No data model is affected.

- **Minimal scope on dependency upgrades.** Pinned third-party
  dependencies (Bokeh, NumPy, SciPy, PyTorch, Pydantic, mozilla-django-oidc,
  django-tables2, etc.) are bumped only as required for compatibility
  with Django 5.2 and Python 3.13. Speculative or "while we're in there"
  upgrades are out of scope for this work. Within that constraint, the
  planner has authority to bump any pinned dependency to whatever
  version compatibility requires — including older pins such as
  `pydantic==2.5.0`, `mozilla-django-oidc==4.0.1`, and
  `django-silk==5.4.3` that may need substantial jumps for Python 3.13
  wheel availability or Django 5.2 API support.

- **GitOps repo PR is merged before this PR.** ArgoCD removes the
  `celery-worker`, `celery-beat`, and `flower` Deployments first; live
  AstroDash pods still contain Celery code at that point but the code
  does nothing (no tasks defined), so dead-but-running code is harmless.
  Then this PR merges and a clean image rolls out without Celery code.
  The inverse order would leave manifests pointing at code that no
  longer exists during the gap, risking crash-looping pods. *Rollback
  contract:* if this PR must be reverted post-merge, re-apply the
  GitOps PR to restore the (inert) Celery Deployments; the system
  returns to the pre-change dead-but-running steady state with no
  broker traffic in flight.

## Requirements

### Django and Python upgrade

- R1. Django is upgraded from 5.1.14 to the latest available 5.2 LTS
  point release at the time the PR is opened.
- R2. Python is upgraded from 3.11 to 3.13 in `app/Dockerfile`
  (including the hardcoded `/usr/local/lib/python3.11/site-packages/`
  path in the multi-stage `COPY --from=deps` instruction), in any
  other interpreter pin (e.g., CI workflow files), and in any
  documentation that names the target Python version.
- R3. Pinned third-party dependencies in `app/requirements.txt` are
  bumped only as required for compatibility with Django 5.2 and
  Python 3.13. No speculative upgrades.

### Celery removal

- R4. Celery and Celery-adjacent dependencies are removed from
  `app/requirements.txt`: `celery`, `flower`, `django-celery-results`,
  and `django-celery-beat`.
- R5. The `celery-worker`, `celery-beat`, and `flower` services are
  removed from `docker/docker-compose.yml`,
  `docker/docker-compose.dev.yaml`, `docker/docker-compose.prod.yaml`,
  and `docker/docker-compose.ci.yaml`.
- R6. Celery integration code and entrypoints are removed:
  `app/astrodash_project/celery.py`, `app/astrodash_project/k8s.py`,
  `app/entrypoints/docker-entrypoint.celery.sh`,
  `app/entrypoints/docker-entrypoint.celery_beat.sh`,
  `app/entrypoints/docker-entrypoint.flower.sh`, and the `celery_app`
  import and `__all__` export in `app/astrodash_project/__init__.py`.
  Celery-only references in `run/astrodashctl` (e.g., `celery-worker`
  in `COMPOSE_LOG_LIST`) are also removed.
- R7. The `CELERY_*` settings block and Celery-related `INSTALLED_APPS`
  entries (`django_celery_beat`, `django_celery_results`) are removed
  from `app/astrodash_project/settings.py`. Other settings unrelated to
  Celery are left untouched.
- R7a. Celery-only environment variables are removed from
  `env/.env.default` (and any other env files): `CELERY_QUEUES`,
  `CELERY_WORKER_LIMIT_CPUS`, `CELERY_WORKER_LIMIT_MEMORY`,
  `DISABLE_CELERY_BEAT`, `MESSAGE_BROKER_HOST`, `MESSAGE_BROKER_PORT`,
  `FLOWER_HOST`, and `FLOWER_PORT`. The `REDIS_*` variables remain
  (Django cache backend; see Dependencies and Assumptions).
- R7b. **Pre-merge check.** Before merge, confirm
  `django_celery_beat_periodictask`,
  `django_celery_beat_intervalschedule`, and
  `django_celery_beat_crontabschedule` contain no enabled rows in the
  production and staging databases. The source-grep audit (zero
  `@shared_task` / `.delay(` matches) does not cover Beat schedules,
  which `DatabaseScheduler` reads from the database. Any enabled rows
  invalidate the "Celery does no work" premise and change scope.

### Documentation

- R8. Documentation no longer states or implies that batch
  classification runs on Celery workers, including `README.md`,
  `docs/admin/updating-data-files.md` (remove the note about celery
  worker / beat pods mounting the data PVC), and
  `docs/developer/getting-started.md` (update the `full_dev` profile
  description). The current synchronous behavior is described
  accurately, with a brief note that async batch processing is a
  future roadmap item.

### Verification

- R9. The existing automated test
  (`app/users/tests/test_user_login.py`) passes under Django 5.2 and
  Python 3.13.
- R10. The application starts cleanly via the named startup profiles
  in `docker-compose.dev`, `docker-compose.prod`, and
  `docker-compose.ci` (i.e., `full_dev`, `full_prod`, `ci`), with no
  errors related to removed Celery imports, settings, services, or
  `INSTALLED_APPS` entries. The `slim_*` profile variants share the
  same Django code path and are not separately exercised by this
  smoke test.
- R11. Single-spectrum classification works end-to-end via the web UI
  (manual smoke test — automated coverage of this path is essentially
  absent in the current codebase).
- R12. Synchronous batch classification at `app/astrodash/views.py:388-410`
  continues to produce results for a small representative input
  (manual smoke test).

## Scope Boundaries

- **Async batch processing architecture.** Deferred to a separate
  brainstorm and plan, to be triggered when batch-async work has
  concrete requirements (throughput targets, failure semantics,
  monitoring needs). The candidate architectures at that time will
  include returning to Celery, adopting `django.tasks`, or another
  task system.
- **Broader dependency sweep.** Major-version upgrades of Bokeh, NumPy,
  SciPy, Pydantic, PyTorch, or any other dependency are out of scope
  unless required for Django 5.2 / Python 3.13 compatibility.
- **Django 6.0 and Python 3.14.** Not the target. Revisit after the
  Django 6.x line publishes an LTS (likely Django 6.2 LTS in April
  2027) and after async-architecture work has resolved.
- **Test suite improvements.** The CI entrypoint at
  `app/entrypoints/docker-entrypoint.app.sh:51` references an
  `astrodash.tests` package that does not exist in the codebase; this
  is a known gap but is separate work and out of scope here.
- **IAM, ecosystem integration, and model library curation.** Active
  strategy tracks per `STRATEGY.md`, but not part of this upgrade.

## Dependencies and Assumptions

- **Kubernetes GitOps repo coordination.** AstroDash deploys via
  ArgoCD from a separate GitOps repository, per `README.md`. That
  repo contains Deployments for `celery-worker`, `celery-beat`, and
  `flower`. Those Deployments must receive paired deletions,
  sequenced per the Key Decision above — the GitOps PR merges before
  this PR — to avoid manifests referencing services that no longer
  ship.
- **Redis stays.** Audit at brainstorm time confirmed Redis is the
  Django cache backend, configured at
  `app/astrodash_project/settings.py:181-184` via
  `django.core.cache.backends.redis.RedisCache`. The `redis` service
  in compose, the `REDIS_*` environment variables, and the `CACHES`
  setting are all retained. Only Celery's use of Redis (broker and
  result backend) goes away.
- **No security advisory or upstream forces a specific timing.** The
  work is proactive hygiene; the PR can be scheduled around other
  release windows.
- **Automated regression coverage is essentially absent.** The only
  automated test in the codebase is
  `app/users/tests/test_user_login.py`. The spectrum-classification
  flows verified in R11 and the synchronous batch path in R12 are
  covered by manual smoke tests only. A Django + Python major-version
  upgrade carries non-trivial regression risk on these untested paths;
  the manual smoke tests are the de facto acceptance gate, not a
  defense-in-depth verification. Adding meaningful automated coverage
  is explicitly out of scope (per Scope Boundaries) but is a known
  risk carried by this PR.

## Sources and Research

- **Django release schedule.** Django 5.2 LTS released April 2025;
  supported through April 2028. Django 5.1 security support ended
  December 2025. Django 6.0 released December 2025; requires Python
  3.12+.
- **Python support matrix.** Django 5.2 supports Python 3.10, 3.11,
  3.12, 3.13. Django 6.0 supports Python 3.12, 3.13. CPython 3.13
  released October 2024 — bugfix support through October 2026,
  security support through October 2029.
- **Django background tasks framework.** `django.tasks` (DEP 0014)
  shipped in Django 6.0. Provides a unified task API with pluggable
  backends (`Immediate`, `Database`). Out of scope for this brainstorm;
  relevant input to the deferred async-architecture decision.
- **Current Celery wiring sites** (for the planner's quick reference):
  - `app/astrodash_project/celery.py` — Celery app construction
  - `app/astrodash_project/k8s.py` — Kubernetes-specific Celery
    bootstep
  - `app/astrodash_project/__init__.py:6,8` — `celery_app` import
    and `__all__` export
  - `app/astrodash_project/settings.py:63,69,170-199` —
    `INSTALLED_APPS` entries and `CELERY_*` config block
  - Zero `@shared_task`, `@app.task`, `.delay(`, or `.apply_async(`
    matches anywhere in `app/` (confirmed by grep at brainstorm time)
- **Current synchronous batch path.** `app/astrodash/views.py:388-410`
  invokes `service.process_batch(...)` wrapped in `async_to_sync`,
  executed in the request thread.

## Deferred / Open Questions

### From 2026-06-10 review

- **Database tables for `django_celery_beat` and `django_celery_results`
  — drop or leave orphaned?** Removing those apps from
  `INSTALLED_APPS` (per R7) leaves the underlying tables and migration
  history in place. The planner must decide whether to (a) write a
  data migration that drops the tables and rolls back the
  `django_celery_*` migration history, or (b) leave the tables
  orphaned and let them be cleaned up in a future schema sweep. The
  right answer depends on actual DB state and operator preference;
  resolve during planning. Raised by adversarial review.
