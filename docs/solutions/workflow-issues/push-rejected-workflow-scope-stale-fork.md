---
title: "Fork push rejected for `workflow` scope when origin/main lags upstream"
date: 2026-08-10
category: workflow-issues
module: Git fork workflow / GitHub Actions
problem_type: workflow_issue
component: development_workflow
severity: medium
applies_when:
  - "Pushing a feature branch to a fork (origin) whose main is behind upstream/main"
  - "The commit range between origin/main and the branch touches .github/workflows/"
  - "Authenticating to GitHub with a Personal Access Token that lacks the workflow scope"
tags: [git, github, workflow-scope, fork, personal-access-token, ci]
---

# Fork push rejected for `workflow` scope when origin/main lags upstream

## Context

This repo uses a fork-based workflow: `origin` is the maintainer's fork
(`github.com/skoranda/astrodash`) and `upstream` is canonical
(`github.com/scimma/astrodash`). Feature branches are cut from local `main`
(kept level with `upstream/main`) and pushed to `origin` to open pull requests.
Inside the VM, git authenticates to GitHub over HTTPS with a `GH_TOKEN`
Personal Access Token.

While preparing a one-line footer fix (issue #51), the branch push to `origin`
was rejected outright:

```
 ! [remote rejected] fix/footer-nsf-disclaimer -> fix/footer-nsf-disclaimer
   (refusing to allow a Personal Access Token to create or update workflow
    `.github/workflows/docker_image_workflow.yml` without `workflow` scope)
error: failed to push some refs to 'https://github.com/skoranda/astrodash.git'
```

The single commit on the branch touched only a Django template
(`app/astrodash/templates/astrodash/base_site.html`) -- nothing under
`.github/workflows/`. The rejection was confusing because the *change* had no
workflow files in it.

## Guidance

The push carries every commit the target ref does not already have, not just
the branch's own commit. When `origin/main` lags `upstream/main`, a branch cut
from the up-to-date local `main` drags along all the intervening merged commits
-- and if any of those touched `.github/workflows/`, GitHub's PAT
`workflow`-scope guard rejects the **entire push**, even though your own commit
is innocent.

Diagnose by listing what the branch adds over the *remote* target and filtering
to workflow paths:

```bash
git fetch origin
git log --oneline origin/main..<branch>                      # full pushed range
git log --oneline origin/main..<branch> -- .github/workflows/ # the offenders
```

If the second command prints anything, that is what trips the guard.

Preferred fix -- get `origin/main` current so the branch's unique range no
longer includes workflow commits (this repo: the maintainer pushes `origin/main`
up to `upstream/main` from a context that has `workflow` scope):

```bash
# after origin/main is fast-forwarded to upstream/main:
git fetch origin
git log --oneline origin/main..<branch> -- .github/workflows/   # now empty
git push -u origin <branch>                                       # succeeds
```

With `origin/main == upstream/main`, the branch's only unique commit is your
own change, the pushed range contains no workflow files, and the scope guard is
never triggered.

Alternative fixes (not used here): grant the PAT the `workflow` scope, or push
from an SSH-keyed context that is not subject to the PAT-scope guard.

## Why This Matters

The error names a workflow file and a missing scope, which misleads you toward
"my change edited a workflow" or "regenerate the token" -- when the real cause
is that the *fork's default branch is stale*. Understanding that a push is
evaluated over the full `remote..branch` commit range (not just your commit)
turns a baffling rejection into a one-line diagnosis, and points at the correct
remedy: sync the fork, don't broaden the token's scope. Keeping a PAT narrow
(no `workflow` scope) is the safer default; syncing `origin/main` preserves that
posture instead of widening the token to work around a stale fork.

## When to Apply

- A `[remote rejected] ... without 'workflow' scope` push failure on a branch
  whose own diff contains no `.github/workflows/` changes
- Any fork whose `main` has fallen behind `upstream` and accumulated merged
  CI/dependency (e.g. Dependabot) commits that edited workflow files
- Before reaching for a broader token scope -- check the stale-fork cause first

## Examples

Before (origin/main stale -- push carries 30 commits, 10 touching workflows):

```
$ git log --oneline origin/main..fix/footer-nsf-disclaimer -- .github/workflows/
3489fd4 Merge pull request #53 ... docker/login-action-4.5.2
edc4bf2 Merge pull request #52 ... actions/checkout-7
e70261a ci: add a GitHub Actions test gate on pull requests and merges
... (7 more)
$ git push -u origin fix/footer-nsf-disclaimer
 ! [remote rejected] ... without `workflow` scope
```

After (origin/main fast-forwarded to upstream/main -- branch adds one commit):

```
$ git log --oneline origin/main..fix/footer-nsf-disclaimer
357e483 fix: update footer NSF disclaimer wording
$ git log --oneline origin/main..fix/footer-nsf-disclaimer -- .github/workflows/
$ git push -u origin fix/footer-nsf-disclaimer
 * [new branch]      fix/footer-nsf-disclaimer -> fix/footer-nsf-disclaimer
```

## Related
- Repo CLAUDE.md "Git workflow" section (fork remotes, VM HTTPS + GH_TOKEN rewrite)
- upstream issue scimma/astrodash#51 (the footer change that surfaced this)
