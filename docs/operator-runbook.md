# Django LTS Upgrade and Celery Removal — Operator Runbook

This runbook covers pre-merge verification, merge sequencing, and post-merge
smoke for the Django 5.2 LTS upgrade and Celery infrastructure removal landed
on `feature/django-lts-upgrade`.

- **Plan:** `docs/plans/2026-06-16-001-refactor-django-lts-upgrade-celery-removal-plan.md`
- **Brainstorm:** `docs/brainstorms/2026-06-10-django-lts-upgrade-celery-removal-requirements.md`
- **Paired GitOps PR (must merge first):** _<link in `astrodash-k8s-gitops`>_

## Prerequisites

Two shell sessions, each with `KUBECONFIG` exported for one cluster:

- **DEV shell** — `KUBECONFIG` points at the dev k3s cluster
- **PROD shell** — `KUBECONFIG` points at the prod k3s cluster

All `kubectl` commands below run with no `--context` flag and no
`KUBECONFIG=...` prefix. Run each command in the shell named at the top of its
block.

Also required:

- Docker available on the laptop for the image build and local compose smoke.
- Local clones of both `astrodash` (GitHub) and `astrodash-k8s-gitops`
  (GitLab) with push access on whichever branches you'll use.
- Network access to <https://astrodash.scimma.org> and
  <https://astrodash-dev.scimma.org> for the UI smoke steps.

PR / merge-request creation and code review happen in each forge's web UI;
all branch creation, diff inspection, merge, and tag operations below use
plain `git`. Substitute your team's preferred merge strategy on the
`git merge` lines if `--no-ff` doesn't match convention.

## Concrete deployment shape (from `astrodash-k8s-gitops`)

These values come directly from the Helm chart at
`astrodash-k8s-gitops/apps/astrodash/` and the ArgoCD Applications. They are
the same on both clusters; the only per-environment differences are the
ingress host and the image tag.

| Resource | Name | Notes |
|---|---|---|
| Namespace | `astrodash` | Set in `argocd-apps/astrodash-{dev,prod}.yaml` and `values.yaml` |
| Helm release name | `astrodash` | All resource names are prefixed `astrodash-` (chart's `fullname` helper returns `Release.Name`) |
| Web Deployment | `astrodash-web` | gunicorn, readiness probe on `/admin/login/` |
| Postgres StatefulSet | `astrodash-postgresql` | replicas: 1 |
| Postgres pod | `astrodash-postgresql-0` | StatefulSet-stable name |
| Postgres Service (DB_HOST) | `astrodash-postgresql` | port 5432 |
| Redis Deployment | `astrodash-redis` | Django cache backend; stays after this work |
| Redis Service | `astrodash-redis` | port 6379 |
| ConfigMap | `astrodash-config` | rendered from `values.yaml`'s `config:` map |
| SealedSecret / Secret | `astrodash-secrets` | carries `DB_PASS`, `DJANGO_SUPERUSER_PASSWORD`, `SECRET_KEY` |
| Image repository | `registry.gitlab.com/ncsa-caps-rse/astrodash-k8s-gitops` | GitLab Container Registry |
| **Pre-removal dev image tag** | `dev9-v1.0.0` | from `values-dev.yaml`; moving tag, `pullPolicy: Always` |
| **Pre-removal prod image tag** | `v1.0.0` | from `values-prod.yaml`; stable, `pullPolicy: IfNotPresent` |

Postgres credentials in-pod: the `postgres` container has `POSTGRES_USER`,
`POSTGRES_PASSWORD`, and `POSTGRES_DB` exported via env (sourced from
`astrodash-config` and `astrodash-secrets`). The runbook uses those directly
rather than fetching the sealed secret out-of-band.

The web Deployment and the (still-deployed) Celery / Beat / Flower Deployments
all pull from `astrodash-secrets` and `astrodash-config` via `envFrom`. The
GitOps PR removes the three Celery Deployments and the Flower Service; ArgoCD
prunes them automatically (`syncPolicy.automated: { prune: true, selfHeal:
true }`).

## What the paired GitOps PR changes

The GitOps PR (must merge first) should make the following changes in
`astrodash-k8s-gitops/apps/astrodash/`:

**Delete:**

- `templates/deployment-celery-worker.yaml`
- `templates/deployment-celery-beat.yaml`
- `templates/deployment-flower.yaml`
- `templates/service-flower.yaml`

**Modify `values.yaml`:**

- Remove the `celeryWorker:` block
- Remove the `celeryBeat:` block
- Remove the `flower:` block
- Under `config:`, remove `CELERY_QUEUES`, `CELERY_CONCURRENCY`,
  `CELERY_MAX_MEMORY_PER_CHILD`, `DISABLE_CELERY_BEAT`, `FLOWER_PORT`,
  `MESSAGE_BROKER_HOST`, and `MESSAGE_BROKER_PORT`. Leave `REDIS_SERVICE`
  in place — it backs the Django cache backend.

The Redis Deployment and Service (`templates/deployment-redis.yaml`,
`templates/service-redis.yaml`) stay. No sealed-secret changes are needed
(none of the encrypted keys reference Celery).

## Step 1 — U1 / R7b: confirm zero enabled Celery Beat rows

The Beat scheduler reads schedule rows from `django_celery_beat_*` tables in
Postgres (not Redis). The source-grep audit doesn't cover these. If any row
in `django_celery_beat_periodictask` has `enabled = true`, the plan's "Celery
does no work" premise fails — halt and reopen scope.

The Postgres container exports `POSTGRES_USER`, `POSTGRES_PASSWORD`, and
`POSTGRES_DB` as env, so the query block authenticates from inside the pod
with no extra secret-fetching on the laptop.

**DEV shell:**

```bash
kubectl -n astrodash exec -i astrodash-postgresql-0 -- bash -c '
  PGPASSWORD="$POSTGRES_PASSWORD" psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "
    SELECT '\''periodictask_enabled'\'' AS counter, count(*) FROM django_celery_beat_periodictask WHERE enabled = true
    UNION ALL
    SELECT '\''periodictask_total'\'',  count(*) FROM django_celery_beat_periodictask
    UNION ALL
    SELECT '\''intervalschedule'\'',    count(*) FROM django_celery_beat_intervalschedule
    UNION ALL
    SELECT '\''crontabschedule'\'',     count(*) FROM django_celery_beat_crontabschedule;
  "
'
```

**PROD shell:** the same block — no substitutions; the resource names are
identical on both clusters.

**Gate:** `periodictask_enabled` must be `0` on both clusters. Other counts
are informational (orphaned schedule rows are harmless until the PR merges).

Record the output verbatim in the "Verification artifact log" at the bottom
of this file. If any cluster returns a non-zero `periodictask_enabled`,
**stop**: inspect the row (`SELECT * FROM django_celery_beat_periodictask
WHERE enabled = true;`), decide whether to disable it manually or revise the
plan, and re-run this step before continuing.

## Gate exceptions encountered

This section records R7b gate exceptions handled during this PR's
verification — what fired, why it was safe to proceed, and how it
resolved. Each entry stays in the runbook permanently as part of the
PR's audit trail.

### celery.backend_cleanup (auto-registered results-table cleanup)

**What fired.** Step 1's R7b query against both clusters returned one
enabled row in `django_celery_beat_periodictask`:

| field | value |
|---|---|
| `task` | `celery.backend_cleanup` |
| `name` | `celery.backend_cleanup` |
| Schedule (cron) | `0 4 * * *` UTC (daily at 04:00 UTC) |
| Status (both clusters at gate check) | `enabled = true` |

**Pre-disable output — Dev (captured 2026-06-16):**

```
 id |          name          |          task          | enabled | crontab_id | interval_id |          last_run_at          | total_run_count |         date_changed          | cs_minute | cs_hour | day_of_week | day_of_month | month_of_year | timezone
----+------------------------+------------------------+---------+------------+-------------+-------------------------------+-----------------+-------------------------------+-----------+---------+-------------+--------------+---------------+----------
  1 | celery.backend_cleanup | celery.backend_cleanup | t       |          1 |             | 2026-06-16 04:00:00.008565+00 |              91 | 2026-06-16 04:03:00.389644+00 | 0         | 4       | *           | *            | *             | UTC
```

**Pre-disable output — Prod (captured 2026-06-16):**

```
 id |          name          |          task          | enabled | crontab_id | interval_id |          last_run_at          | total_run_count |         date_changed          | cs_minute | cs_hour | day_of_week | day_of_month | month_of_year | timezone
----+------------------------+------------------------+---------+------------+-------------+-------------------------------+-----------------+-------------------------------+-----------+---------+-------------+--------------+---------------+----------
  1 | celery.backend_cleanup | celery.backend_cleanup | t       |          1 |             | 2026-06-16 04:00:00.009381+00 |              89 | 2026-06-16 04:01:25.206678+00 | 0         | 4       | *           | *            | *             | UTC
```

**Why this is a safe exception.** `celery.backend_cleanup` is the
auto-registered cleanup task that `django-celery-beat` installs by
default when `django_celery_results` is in `INSTALLED_APPS`. Its sole
job is to expire rows in `django_celery_results_taskresult` — the
same results table that goes orphaned when this PR ships (see Plan
§ Key Technical Decisions, "Leave orphaned `django_celery_beat_*`
and `django_celery_results_*` tables"). No application work runs
through it.

The R7b gate language was conservative on purpose ("any enabled rows
invalidate the 'Celery does no work' premise"). Auto-registered
plumbing for infrastructure already scheduled for removal in the
same change window is not the failure mode that gate was designed to
catch.

**Disable action — both clusters:**

`UPDATE` rather than `DELETE` so the change is fully reversible and
the row goes orphaned with the rest of `django_celery_beat_*` when
the PR ships.

```bash
kubectl -n astrodash exec -i astrodash-postgresql-0 -- bash -c '
  PGPASSWORD="$POSTGRES_PASSWORD" psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "
    UPDATE django_celery_beat_periodictask
    SET enabled = false
    WHERE task = '\''celery.backend_cleanup'\'' AND enabled = true
    RETURNING id, name, task, enabled;
  "
'
```

The `RETURNING` clause prints the row's new state. Expect
`enabled | f` on the one row.

**Post-disable re-verify — Dev (captured 2026-06-16):**

```
       counter        | count
----------------------+-------
 periodictask_enabled |     0
 periodictask_total   |     1
 intervalschedule     |     0
 crontabschedule      |     1
(4 rows)
```

**Post-disable re-verify — Prod (captured 2026-06-16):**

```
       counter        | count
----------------------+-------
 periodictask_enabled |     0
 periodictask_total   |     1
 intervalschedule     |     0
 crontabschedule      |     1
(4 rows)
```

The gate cleared on both clusters: `periodictask_enabled = 0`.
`periodictask_total = 1` reflects the disabled `celery.backend_cleanup`
row still present in the table; it goes orphaned with the rest of
`django_celery_beat_*` when the PR ships, per the plan's Key
Technical Decision on table cleanup.

**Rollback note.** If the GitOps PR revert restores the inert Celery
Deployments before the prod tag bump (see § Rollback contract), the
`celery.backend_cleanup` row stays in place but disabled — nightly
cleanup will not run under the restored infrastructure. An operator
who wants the cleanup to resume during a rollback window can
re-enable it:

```bash
kubectl -n astrodash exec -i astrodash-postgresql-0 -- bash -c '
  PGPASSWORD="$POSTGRES_PASSWORD" psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "
    UPDATE django_celery_beat_periodictask
    SET enabled = true
    WHERE task = '\''celery.backend_cleanup'\'';
  "
'
```

## Step 2 — U5: build the image and run the cp313 PyTorch wheel probe (laptop)

Laptop-side work — no kubectl required.

```bash
cd /mnt/pophome/CAPS/SCiMMA/DASH/astrodash

# Probe cp313 wheel availability before building
pip download --no-deps \
  --python-version 3.13 \
  --only-binary=:all: \
  --platform manylinux_2_28_x86_64 \
  --index-url https://download.pytorch.org/whl/cpu \
  torch==2.9.0+cpu torchvision==0.24.0 \
  -d /tmp/wheel-probe/
# Success: torch-2.9.0+cpu-cp313-*.whl and torchvision-0.24.0-cp313-*.whl
#   land in /tmp/wheel-probe/.
# Failure: "ERROR: Could not find a version that satisfies the requirement".
#   In that case bump torch / torchvision in app/Dockerfile to the earliest
#   versions that publish cp313 wheels, amend the U5 commit, and re-probe.

# Build the deps stage, then the runtime image
docker build --target deps -f app/Dockerfile -t astrodash:deps-py3.13 app/
docker build -f app/Dockerfile -t astrodash:django-5.2-py3.13 app/
# If pip surfaces compatibility errors for pydantic, pydantic-settings,
# mozilla-django-oidc, django-silk, or psycopg2-binary, bump those pins
# in app/requirements.txt, amend the U5 commit, and re-build.

# Confirm Celery is fully gone from the resolved deps
docker run --rm astrodash:django-5.2-py3.13 \
  pip show celery flower django-celery-beat django-celery-results
# Expect: "WARNING: Package(s) not found: celery, flower,
#   django-celery-beat, django-celery-results"

# Django boots and check passes
docker run --rm astrodash:django-5.2-py3.13 \
  python -c "from astrodash_project import settings; print('settings import OK')"
docker run --rm astrodash:django-5.2-py3.13 python manage.py check
# Expect: "System check identified no issues (0 silenced)."

# Print landed versions for the PR description
docker run --rm astrodash:django-5.2-py3.13 python --version
docker run --rm astrodash:django-5.2-py3.13 \
  python -c "import django; print('Django', django.get_version())"

# Existing automated test
docker run --rm astrodash:django-5.2-py3.13 python manage.py test users.tests
# Expect: "Ran 1 test in <time>s — OK"
```

Record the wheel-probe outcome, the landed Python and Django versions, the
`users.tests` outcome, and any pin bumps you had to apply in the verification
artifact log.

## Step 3 — Author and merge the paired GitOps MR; watch dev reconcile

**DEV shell** before authoring, re-run the U1 / R7b check — data may have
changed since Step 1. Same block as Step 1; same gate (`periodictask_enabled`
must be `0`).

### 3a. Create a branch in `astrodash-k8s-gitops`

The Celery-removal MR does not exist yet — you author it now. In your
local `astrodash-k8s-gitops` clone:

```bash
cd <path to astrodash-k8s-gitops working tree>
git checkout main
git pull --ff-only origin main
git checkout -b refactor/remove-inert-celery   # name to taste
```

### 3b. Delete the four Celery / Flower templates

```bash
git rm apps/astrodash/templates/deployment-celery-worker.yaml
git rm apps/astrodash/templates/deployment-celery-beat.yaml
git rm apps/astrodash/templates/deployment-flower.yaml
git rm apps/astrodash/templates/service-flower.yaml
```

### 3c. Edit `apps/astrodash/values.yaml`

Open the file in your editor and remove three contiguous blocks and seven
config keys. Exact text to delete:

**Block 1 — the celeryWorker block (currently around lines 25–34):**

```yaml

# --- Celery Worker ---
celeryWorker:
  replicas: 1
  resources:
    requests:
      cpu: "100m"
      memory: "512Mi"
    limits:
      cpu: "500m"
      memory: "1536Mi"
```

**Block 2 — the celeryBeat block (around lines 36–45):**

```yaml

# --- Celery Beat ---
celeryBeat:
  enabled: true
  resources:
    requests:
      cpu: "50m"
      memory: "256Mi"
    limits:
      cpu: "200m"
      memory: "512Mi"
```

**Block 3 — the flower block (around lines 47–57):**

```yaml

# --- Flower ---
flower:
  enabled: true
  port: 8888
  resources:
    requests:
      cpu: "50m"
      memory: "256Mi"
    limits:
      cpu: "200m"
      memory: "512Mi"
```

**Config keys to remove (under `config:`, currently around lines 95–116):**

```yaml
  MESSAGE_BROKER_HOST: "astrodash-redis"
  MESSAGE_BROKER_PORT: "6379"
  CELERY_QUEUES: "celery"
  CELERY_CONCURRENCY: "4"
  CELERY_MAX_MEMORY_PER_CHILD: "12000"
  DISABLE_CELERY_BEAT: "false"
  FLOWER_PORT: "8888"
```

Leave the rest of the `config:` map intact — in particular `REDIS_SERVICE:
"astrodash-redis"` stays (Django cache backend).

### 3d. Verify, commit, push

```bash
# Inspect changes
git status
git diff apps/astrodash/values.yaml
git diff --name-only main..
# Expect: four deletions under apps/astrodash/templates/ plus
#   one modification to apps/astrodash/values.yaml.

# Verify no orphaned chart references remain — templates that still expect
# the removed Helm values, or other consumers of the dropped configmap keys
grep -rn "\.Values\.\(celeryWorker\|celeryBeat\|flower\)\|MESSAGE_BROKER\|FLOWER_PORT\|CELERY_" apps/astrodash/ \
  || echo "OK: no orphaned references"
# Expect: only the "OK" line. Any grep hit names a file that needs follow-up.

# Sanity-check the Helm chart still templates (catches indentation breakage
# in values.yaml). Requires helm CLI; skip if helm is not installed locally.
helm template astrodash apps/astrodash -f apps/astrodash/values.yaml \
  -f apps/astrodash/values-dev.yaml >/dev/null && echo "dev values template OK"
helm template astrodash apps/astrodash -f apps/astrodash/values.yaml \
  -f apps/astrodash/values-prod.yaml >/dev/null && echo "prod values template OK"

# Stage and commit
git add apps/astrodash/values.yaml
git commit -m "refactor: remove inert Celery infrastructure

Paired with the AstroDash code PR for the Django 5.2 LTS upgrade
(see astrodash docs/plans/2026-06-16-001-refactor-django-lts-upgrade-celery-removal-plan.md).

Removes:
- Celery worker, Celery Beat, and Flower Deployments
- Flower Service
- celeryWorker, celeryBeat, and flower blocks from values.yaml
- CELERY_*, FLOWER_PORT, and MESSAGE_BROKER_* keys from values.yaml config

Redis Deployment, Service, and the REDIS_SERVICE config key stay
in place — Django uses Redis as its cache backend.

ArgoCD auto-syncs both clusters with prune+selfHeal, so the four
removed resources disappear automatically once this MR merges. The
running app Deployments on dev and prod still contain Celery code
at that point but the code does nothing (no tasks defined), so the
dead-but-running code is harmless until the AstroDash code PR's
image rolls out."

git push origin refactor/remove-inert-celery
```

### 3e. Open MR, review, merge

Open the merge request in the GitLab web UI at
<https://gitlab.com/ncsa-caps-rse/astrodash-k8s-gitops>, request review,
and either click the merge button there once approved or merge locally:

```bash
git checkout main
git pull --ff-only origin main
git merge --no-ff refactor/remove-inert-celery \
  -m "Merge refactor/remove-inert-celery: remove inert Celery infrastructure"
git push origin main
```

Capture the merge-commit SHA from `git log -1 --format=%H` — it's the
input to the `git revert -m 1 <sha>` step in the Rollback contract
section if a revert is ever needed.

**DEV shell** — watch ArgoCD prune the Celery Deployments. The dev cluster
auto-syncs immediately because dev runs the moving tag with
`pullPolicy: Always`.

```bash
kubectl -n astrodash get pods -w
# Expect: astrodash-celery-worker-*, astrodash-celery-beat-*,
#   astrodash-flower-* pods enter Terminating within ~30s of the merge
#   (syncPolicy.automated.prune is on). Ctrl-C once they're gone.

kubectl -n astrodash get deploy
# Expect: only astrodash-web and astrodash-redis remain.
#   No astrodash-celery-worker / astrodash-celery-beat / astrodash-flower.

kubectl -n astrodash get svc
# Expect: no astrodash-flower Service.
```

**PROD shell** — confirm prod Deployments and Service are also pruned (the
same GitOps PR covers both env values files):

```bash
kubectl -n astrodash get deploy
kubectl -n astrodash get svc
# Expect: no astrodash-celery-* / astrodash-flower resources.
# The astrodash-web Deployment is still running the pre-removal image
# (registry.gitlab.com/ncsa-caps-rse/astrodash-k8s-gitops:v1.0.0) —
# that's the "dead-but-running steady state" until Step 6.
```

## Step 4 — Merge the code PR and tag a release

On the laptop:

```bash
cd /mnt/pophome/CAPS/SCiMMA/DASH/astrodash
git checkout feature/django-lts-upgrade
git push origin feature/django-lts-upgrade
```

Open the PR in the GitHub web UI at <https://github.com/scimma/astrodash>,
request review, and use the PR description template at the bottom of this
file (paste it into the description field, or reference `docs/operator-runbook.md`
inline).

After review approval, either click the merge button in the GitHub UI or
merge locally:

```bash
git checkout main
git pull --ff-only origin main
git merge --no-ff feature/django-lts-upgrade \
  -m "refactor: Django 5.2 LTS upgrade and Celery infrastructure removal"
git push origin main
```

Then tag a release to trigger the image build/push.
`.github/workflows/docker_image_workflow.yml` builds and pushes on tag
push, not on every merge:

```bash
git checkout main
git pull --ff-only origin main
git tag v<X.Y.Z>          # bump per your SemVer convention
git push origin v<X.Y.Z>
```

The CI workflow pushes the image to
`registry.gitlab.com/ncsa-caps-rse/astrodash-k8s-gitops:v<X.Y.Z>`.

**DEV shell** — dev auto-syncs on the moving tag (`dev<N>-v<X.Y.Z>` is
maintained by your release convention; if you bump the dev tag in
`values-dev.yaml` as part of the GitOps PR, the rollout fires there).
Confirm the rollout:

```bash
kubectl -n astrodash rollout status deploy/astrodash-web --timeout=10m
kubectl -n astrodash get deploy astrodash-web \
  -o jsonpath='{.spec.template.spec.containers[0].image}'
# Confirm the image tag is the new release.
```

## Step 5 — Smoke dev (R10 / R11 / R12 / R13)

**DEV shell:**

```bash
# R11 readiness — the readiness probe target returns 200 with the right Host
curl -sf -H 'Host: astrodash-dev.scimma.org' \
  https://astrodash-dev.scimma.org/admin/login/ -o /dev/null \
  && echo "OK: dev /admin/login/ 200"

# R10 — users.tests under the deployed image
kubectl -n astrodash exec -i deploy/astrodash-web -- \
  python manage.py test users.tests
# Expect: "Ran 1 test ... OK"
```

**Laptop** — local compose smoke (independent verification surface):

```bash
cd /mnt/pophome/CAPS/SCiMMA/DASH/astrodash

# full_dev
run/astrodashctl full_dev up
# Visit http://localhost:4000/astrodash/ — confirm web reaches the landing
run/astrodashctl full_dev down

# full_prod (requires env/.env.prod populated locally)
run/astrodashctl full_prod up
run/astrodashctl full_prod down

# ci profile — uses the U7 step-4 command override the plan committed
docker compose \
  -f docker/docker-compose.yml \
  -f docker/docker-compose.ci.yaml \
  --profile ci run --rm app \
  coverage run manage.py test --exclude-tag=download users.tests
# Expect: exit 0, "Ran 1 test ... OK"
```

**UI smoke (manual, on the dev environment):**

- R12 — Visit <https://astrodash-dev.scimma.org/astrodash/>, upload a known
  spectrum, confirm a classification result is returned and rendered.
- R13 — Submit a small representative batch (2–3 spectra), confirm results
  return synchronously (no celery, no flower, no Redis broker traffic).

Record outcomes in the verification artifact log.

## Step 6 — Promote to prod (controlled, manual)

In your local `astrodash-k8s-gitops` clone:

```bash
cd <path to astrodash-k8s-gitops working tree>
git checkout main
git pull --ff-only origin main
git checkout -b chore/bump-prod-v<X.Y.Z>

# Edit apps/astrodash/values-prod.yaml: change image.tag from v1.0.0 to v<X.Y.Z>.
# Prod uses pullPolicy: IfNotPresent, so the tag bump itself is the
# trigger for the rollout.

git add apps/astrodash/values-prod.yaml
git commit -m "chore: bump prod image to v<X.Y.Z> (post-Celery)

Promotes the Django 5.2 LTS / Celery removal to prod. Pre-removal tag
was v1.0.0; rollback contract closes after this MR merges."
git push origin chore/bump-prod-v<X.Y.Z>
```

Open the merge request in the GitLab web UI for review. After approval,
either merge in the UI or locally:

```bash
git checkout main
git pull --ff-only origin main
git merge --no-ff chore/bump-prod-v<X.Y.Z> \
  -m "chore: bump prod image to v<X.Y.Z> (post-Celery)"
git push origin main
```

**PROD shell** — watch the prod rollout and smoke:

```bash
kubectl -n astrodash rollout status deploy/astrodash-web --timeout=10m
kubectl -n astrodash get deploy astrodash-web \
  -o jsonpath='{.spec.template.spec.containers[0].image}'
# Confirm image tag = v<X.Y.Z>.

# Readiness
curl -sf -H 'Host: astrodash.scimma.org' \
  https://astrodash.scimma.org/admin/login/ -o /dev/null \
  && echo "OK: prod /admin/login/ 200"

# users.tests under the prod image
kubectl -n astrodash exec -i deploy/astrodash-web -- \
  python manage.py test users.tests
```

**Prod UI smoke (manual):**

- Visit <https://astrodash.scimma.org/astrodash/>, run the same single-spectrum
  and batch-classification flows as in Step 5.

## Rollback contract

Rollback semantics are time-bounded by the prod tag bump in Step 6.

- **Before the prod tag bump** — re-applying the GitOps PR revert restores
  the (inert) Celery Deployments on prod against the pre-removal image
  (`registry.gitlab.com/ncsa-caps-rse/astrodash-k8s-gitops:v1.0.0`, still
  running). The system returns to the pre-change dead-but-running steady
  state.
- **After the prod tag bump** — prod is on the post-removal image, which no
  longer carries the Celery entrypoint scripts or the celery binary.
  Re-applying the GitOps PR revert would land restored celery pods in
  CrashLoopBackOff against the new image. Forward fix is the only path.

If a rollback is needed before the prod tag bump:

```bash
cd <path to astrodash-k8s-gitops working tree>
git checkout main
git pull --ff-only origin main
git checkout -b revert/restore-inert-celery-deployments

# Revert the merge commit that landed the Celery-removal MR. -m 1 says
# "treat main as the first parent, so this revert undoes the changes
# that came from the feature branch (the second parent)."
git revert -m 1 <merge-commit-sha-of-the-Celery-removal-MR>

git push origin revert/restore-inert-celery-deployments
```

Open the merge request in the GitLab web UI for review. After approval,
either merge in the UI or locally:

```bash
git checkout main
git pull --ff-only origin main
git merge --no-ff revert/restore-inert-celery-deployments \
  -m "revert: restore inert Celery Deployments (rollback contract)"
git push origin main
```

**PROD shell:**

```bash
kubectl -n astrodash get deploy -w
# Expect astrodash-celery-worker, astrodash-celery-beat, astrodash-flower
# Deployments return, pulling v1.0.0, idle on the empty queue.
```

## Verification artifact log

Fill in as steps complete. The completed log is the verification artifact
captured by the PR description.

### Step 1 — R7b DB check

**Dev** (captured 2026-06-16):

```
counter              | count
---------------------+-------
periodictask_enabled |     1
periodictask_total   |     1
intervalschedule     |     0
crontabschedule      |     1
```

**Prod** (captured 2026-06-16):

```
counter              | count
---------------------+-------
periodictask_enabled |     1
periodictask_total   |     1
intervalschedule     |     0
crontabschedule      |     1
```

Gate fired on `periodictask_enabled = 1` on both clusters. See
§ Gate exceptions encountered → celery.backend_cleanup for the
diagnosis, disable action, and re-verify outputs.

### Step 2 — U5 build and probe (captured 2026-06-16)

- **cp313 wheel probe:**
  - `torch-2.9.0+cpu-cp313-cp313-manylinux_2_28_x86_64.whl` (184.4 MB) — confirmed
  - `torchvision-0.24.0+cpu-cp313-cp313-manylinux_2_28_x86_64.whl` (1.9 MB) — confirmed
- **Landed Python version:** 3.13.14
- **Landed Django version:** 5.2.6
- **Pin bumps applied during build:**
  - `pydantic` 2.5.0 → 2.9.2 (forced — pydantic-core 2.14.1 has no cp313 wheel and source build fails on `ForwardRef._evaluate()` signature change in Python 3.13). Landed via commit `refactor: bump pydantic to 2.9.2 for cp313 wheel availability (U5)`.
  - `pydantic-settings` 2.1.0 → 2.5.2 (paired with pydantic 2.9.2).
  - No other flagged candidates (`mozilla-django-oidc`, `django-silk`, `psycopg2-binary`) needed bumping — dry-run install probes resolved cleanly under cp313.
- **Image:** `astrodash:django-5.2-py3.13` built clean (deps stage + runtime stage; 533 MB content size).
- **Celery cleanup verification:** `pip show celery flower django-celery-beat django-celery-results` inside the new image returned `WARNING: Package(s) not found: celery, django-celery-beat, django-celery-results, flower`. PASS.
- **Settings import:** `python -c "from astrodash_project import settings; print('settings import OK')"` exits zero with the expected output. PASS.
- **`python manage.py check`:** `System check identified no issues (0 silenced).` PASS.
- **`users.tests` (SQLite, in-memory):** 1 test, OK in 0.190s. PASS.
- **`users.tests` (Postgres-backed, via dev/prod clusters):** deferred to Step 5 / Step 6 smoke matrix.

### Step 4 — Image rollout

- Pre-removal dev image tag (rollback fallback): `registry.gitlab.com/ncsa-caps-rse/astrodash-k8s-gitops:dev9-v1.0.0`
- Pre-removal prod image tag (rollback fallback): `registry.gitlab.com/ncsa-caps-rse/astrodash-k8s-gitops:v1.0.0`
- Released tag: v___________
- Dev image observed after rollout: ___________

### Step 5 — Dev smoke

- Dev `/admin/login/` 200: PASS / FAIL
- Dev `users.tests`: PASS / FAIL
- Local `full_dev` compose boot: PASS / FAIL
- Local `full_prod` compose boot: PASS / FAIL
- Local `ci` profile `users.tests`: PASS / FAIL
- Dev single-spectrum classification: PASS / FAIL
- Dev synchronous batch classification: PASS / FAIL

### Step 6 — Prod promotion

- Prod image observed after rollout: ___________
- Prod `/admin/login/` 200: PASS / FAIL
- Prod `users.tests`: PASS / FAIL
- Prod single-spectrum classification: PASS / FAIL
- Prod synchronous batch classification: PASS / FAIL

## PR description template (optional copy/paste)

```markdown
## Summary

Upgrades Django 5.1.14 → 5.2 LTS and Python 3.11 → 3.13; removes
inert Celery infrastructure (deps, services, settings, integration
code, entrypoints, env vars, docs).

## Plan / Brainstorm

- Plan: `docs/plans/2026-06-16-001-refactor-django-lts-upgrade-celery-removal-plan.md`
- Brainstorm: `docs/brainstorms/2026-06-10-django-lts-upgrade-celery-removal-requirements.md`
- Operator runbook: `docs/operator-runbook.md`

## Paired GitOps PR

<link to astrodash-k8s-gitops PR — merged at <timestamp>>

## Pre-removal image tags (rollback fallback)

- Dev: `registry.gitlab.com/ncsa-caps-rse/astrodash-k8s-gitops:dev9-v1.0.0`
- Prod: `registry.gitlab.com/ncsa-caps-rse/astrodash-k8s-gitops:v1.0.0`

Rollback is viable only before the prod tag bump in `values-prod.yaml`
(see runbook § Rollback contract).

## Verification

See the filled-in verification artifact log in
`docs/operator-runbook.md` § Verification artifact log.
```
