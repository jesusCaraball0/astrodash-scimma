# Brainstorm: Integrate Contributor Commits from Fork

**Date:** 2026-03-09
**Status:** Ready for planning

## What We're Building

A process to integrate 21 commits from a contributor's fork (https://github.com/jesusCaraball0/blast) into the excised astrodash codebase. The fork was made from `main` before the Blast excision, so the contributor's changes are based on the old Blast repo structure.

## Why This Approach

**Diff-and-apply on a new branch** is the best fit because:
- The excision fundamentally changed repo structure (renamed Django project, removed host/, api/, etc.)
- Git merge/rebase would produce excessive, confusing conflicts from structural divergence
- A patch-based approach lets us surgically apply only relevant changes
- Working on a new branch off `feature/astrodash_excise` preserves the excision work as a clean fallback
- Squashing is acceptable, so losing individual commit history is not a concern

## Key Decisions

1. **Approach:** Diff-and-apply (generate patch from fork, apply to excised branch)
2. **Branch strategy:** New branch off `feature/astrodash_excise` (not directly on it)
3. **Commit history:** Squash into one or a few logical commits (individual history not needed)
4. **Scope:** Primarily `app/astrodash/` changes; non-astrodash changes (settings, requirements, etc.) reviewed and applied manually
5. **Fork base:** Contributor forked from `main`

## Process Outline

1. Add contributor's fork as a remote
2. Fetch their commits
3. Identify the fork point (common ancestor with `main`)
4. Generate a diff of the 21 commits against the fork point
5. Filter/split the diff: astrodash-only changes vs. shared file changes
6. Create new branch off `feature/astrodash_excise`
7. Apply the astrodash patch, resolve any conflicts
8. Manually review and apply non-astrodash changes
9. Test the result
10. Commit with attribution to the contributor

## Open Questions

- What branch did the contributor work on? (main, or a feature branch?)
- Are there any commits that should be excluded (e.g., merge commits, experimental work)?
- Should the contributor be listed as co-author in the squashed commit?
