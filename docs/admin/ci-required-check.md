# Making the Test Suite a Required Check

The `Tests` workflow (`.github/workflows/test.yml`) runs the automated suite on
every pull request and on merges to `main`. Running it is not enough to protect
`main` -- a maintainer must mark it a **required status check** in branch
protection so a red run blocks the merge. Branch protection is a repository
Settings action; it cannot be set from code, so it is documented here.

## The check name

The required status check is the workflow job name:

```
test-suite
```

In the branch-protection UI it appears as `test-suite` (GitHub may render it as
`Tests / test-suite`). If the job is ever renamed in `test.yml`, update the
required check on both repositories to match, or the gate silently stops binding.

## Ordering (important)

Enable the required check on a repository **only after** the `Tests` workflow is
present on that repository's `main`. A required check that names a workflow not
yet on `main` blocks every pull request while it waits for a check that can
never run. So, per repository: merge the workflow to `main` first, confirm one
run has appeared under a pull request, then add it as required.

## Enable on both repositories

Set the required check on both the fork and the canonical repository:

- `origin` -- `github.com/skoranda/astrodash`, branch `main`
- `upstream` -- `github.com/scimma/astrodash`, branch `main`

For each repository:

1. Settings -> Branches -> Branch protection rules -> add or edit the rule for
   `main`.
2. Enable **Require status checks to pass before merging**.
3. Add `test-suite` to the required checks. (It only appears in the picker after
   the workflow has run at least once on that repository -- see Ordering above.)
4. Save.

Optionally enable **Require branches to be up to date before merging** so a PR
must re-run against the current `main` before it can merge.

## Notes

- The workflow uses the `pull_request` event, so **pull requests from forks run
  with no repository secrets** and a read-only token. The suite needs neither,
  so fork PRs are gated the same as internal ones without exposing secrets.
- The workflow builds the app image and runs the existing container test target;
  it does not deploy. The tag-triggered image-publish workflow
  (`docker_image_workflow.yml`) is separate and unaffected.
