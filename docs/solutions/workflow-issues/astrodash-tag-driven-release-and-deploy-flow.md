---
title: "AstroDash tag-driven release and deploy flow (build tag -> gitops image.tag -> ArgoCD)"
date: 2026-08-10
category: workflow-issues
module: Release / CI-CD / GitOps deploy
problem_type: workflow_issue
component: development_workflow
severity: medium
applies_when:
  - "Cutting a DEV test build or a PROD release of AstroDash"
  - "A code change is merged upstream and needs to reach DEV or PROD"
  - "Deciding which tag name and which gitops values file to touch for a rollout"
tags: [release, deploy, argocd, gitops, docker-tag, ci-cd, versioning]
---

# AstroDash tag-driven release and deploy flow (build tag -> gitops image.tag -> ArgoCD)

## Context

AstroDash has two decoupled halves that together make a deploy: a **git tag on
`upstream` builds an image**, and a **gitops `image.tag` bump drives the
rollout**. They are separate actions in separate repos, and conflating them (or
doing them in the wrong order) leaves either an image nobody is running or a
values file pointing at an image that does not exist yet. This documents the
full round trip, captured while shipping `v1.1.0` (and its `dev4-v1.1.0` and
`dev5-v1.1.0` test builds).

## Guidance

**Two axes, two tag shapes.** `.github/workflows/docker_image_workflow.yml`
fires only on tags matching two patterns
(`.github/workflows/docker_image_workflow.yml:5-7`):

- `dev[0-9]-v<X.Y.Z>` -> builds `registry.gitlab.com/ncsa-caps-rse/astrodash-k8s-gitops:<tag>` **and** `:dev` (`docker_image_workflow.yml:33`)
- `v<X.Y.Z>` -> builds `...:<tag>` **and** `:latest` (`docker_image_workflow.yml:30`)

Tag-shape convention (match it): **DEV tags are lightweight**, **release tags
are annotated** with message `"vX.Y.Z SCiMMA Astrodash"` (mirrors the existing
`v1.0.0` tag).

**Push tags to `upstream`, not `origin`.** The build only runs where the GitLab
registry secrets live -- the canonical `scimma/astrodash` repo. Prior dev/release
tags exist on `upstream` and nowhere on `origin`; a tag pushed to `origin` builds
nothing.

**The rollout is a one-line gitops edit on `main`.** The deploy repo is
`../astrodash-k8s-gitops`; both ArgoCD apps track `targetRevision: HEAD` (= the
default branch `main`) with `path: apps/astrodash`
(`astrodash-k8s-gitops/argocd-apps/astrodash-dev.yaml:10-11`). Bump the
environment's `image.tag` (paths below are in the gitops repo, not this one):

- DEV -> `astrodash-k8s-gitops/apps/astrodash/values-dev.yaml` (`pullPolicy: Always`)
- PROD -> `astrodash-k8s-gitops/apps/astrodash/values-prod.yaml` (`pullPolicy: IfNotPresent`)

Commit the bump **directly to `main`** (the established convention, e.g. commit
`chore: update dev image tag to dev5-v1.1.0`) and push. ArgoCD reconciles main
and rolls the pods. Note the gitops remote is **GitLab over SSH**, which the VM
cannot push -- the maintainer pushes the gitops commit from the host.

**End-to-end order (DEV shown; PROD is identical with the `v<X.Y.Z>` tag and
`values-prod.yaml`):**

1. `git tag dev5-v1.1.0 <commit>` (lightweight) -> `git push upstream dev5-v1.1.0`
2. Wait for the Actions build to go green **before** the gitops bump, or ArgoCD
   pulls a tag that is not in the registry yet
   (`gh run watch <id> --repo scimma/astrodash`)
3. In gitops on `main`: `values-dev.yaml` `tag:` -> `dev5-v1.1.0`, commit, push
4. Verify the rollout (below)

**Verify via the footer, not `/healthz`.** `settings.APP_VERSION` resolves from
the `APP_VERSION` env var, which the Helm chart sets from `.Values.image.tag`,
falling back to the literal `local` (`app/astrodash_project/settings.py:33`).
The rendered surface is the footer, which links to
`releases/tag/{app_version}` (`base_site.html:189`). Despite references to a
`/healthz` payload in comments, **no `/healthz` route is currently registered**
-- that path 404s. Scrape the footer instead:

```bash
curl -s https://astrodash-dev.scimma.org/astrodash/ \
  | grep -oE 'releases/tag/[^"]+' | head -1   # -> releases/tag/dev5-v1.1.0
```

Expect a brief window during the rollout where the pod is restarting and the
scrape returns nothing before the new tag appears.

## Why This Matters

The build axis and the deploy axis are independent, so the failure modes are
silent: tag `origin` and nothing builds; bump the gitops tag before the build
finishes and ArgoCD wedges on an ImagePullBackOff; edit the wrong values file
and the other environment moves. Knowing that a deploy is exactly "tag upstream
-> confirm image -> bump `image.tag` on gitops main -> ArgoCD reconciles"
collapses a multi-repo, multi-actor process into four unambiguous steps, and
makes the DEV-then-PROD promotion (same commit, `dev[N]-v1.1.0` then `v1.1.0`)
routine.

## When to Apply

- Promoting a merged change to DEV for testing, then to PROD
- Any time the running version needs to change (the footer version is the check)
- Diagnosing "I pushed a tag but nothing deployed" (wrong remote, or missing
  gitops bump) or "ArgoCD can't pull the image" (bumped before the build was green)

## Examples

DEV test build:

```bash
git tag dev5-v1.1.0 6ee8595                 # lightweight dev tag
git push upstream dev5-v1.1.0               # builds :dev5-v1.1.0 and :dev
# ... build green ...
# gitops main: values-dev.yaml  tag: dev4-v1.1.0 -> dev5-v1.1.0
git commit -am "chore: update dev image tag to dev5-v1.1.0" && git push origin main
```

PROD release (same commit, promoted after DEV testing):

```bash
git tag -a v1.1.0 -m "v1.1.0 SCiMMA Astrodash" 6ee8595   # annotated release tag
git push upstream v1.1.0                                   # builds :v1.1.0 and :latest
# gitops main: values-prod.yaml  tag: v1.0.0 -> v1.1.0
git commit -am "chore: update prod image tag to v1.1.0" && git push origin main
```

## Related
- Repo CLAUDE.md "Versioning (APP_VERSION)" and "Deployment and the gitops repo" sections
- `docs/solutions/workflow-issues/push-rejected-workflow-scope-stale-fork.md` (fork-push gotcha in the same tag/push workflow)
- Companion gitops repo: `../astrodash-k8s-gitops` (Helm chart, per-env values, ArgoCD apps)
