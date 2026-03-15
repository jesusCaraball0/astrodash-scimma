# Brainstorm: Update CI to Push Images to GitLab Container Registry

**Date:** 2026-03-15
**Status:** Ready for planning

## What We're Building

Update the existing GitHub Actions workflow (`docker_image_workflow.yml`) to build the astrodash Docker image and push it to the GitLab Container Registry at `registry.gitlab.com/ncsa-caps-rse/astrodash-k8s-gitops`. This is where the Kubernetes deployment (managed by ArgoCD) pulls images from.

The current workflow is a holdover from the old Blast application. It builds images and attempts to push, but has no registry login step and uses bare image names with no registry prefix — so pushes fail silently.

## Why This Approach

**Chosen: Update the existing GitHub Actions workflow to push to GitLab registry**

The app source code lives in GitHub, so GitHub Actions is the natural CI system. The GitOps repo is in GitLab, and GitLab Container Registry is already configured as the image source in the Helm chart. The workflow just needs:
1. A `docker/login-action` step targeting `registry.gitlab.com`
2. Updated image tags with the full registry prefix
3. GitLab deploy token credentials stored as GitHub Actions secrets

**Rejected alternatives:**
- **Migrate CI to GitLab CI:** Would require mirroring the source repo to GitLab. Unnecessary complexity.
- **Use Docker Hub:** The Kubernetes imagePullSecret and Helm chart are already configured for GitLab registry.

## Key Decisions

- **Trigger:** Keep tag-only triggers (`v*` and `dev*` tags), no change
- **Registry:** `registry.gitlab.com/ncsa-caps-rse/astrodash-k8s-gitops`
- **Auth:** Reuse existing deploy token (`gitlab+deploy-token-12722131`), stored as GitHub Actions secrets `GITLAB_REGISTRY_USER` and `GITLAB_REGISTRY_TOKEN`
- **Tag strategy:** Keep current — `v*` tags produce `:version` + `:latest`, `dev*` tags produce `:version` + `:dev`
- **Tests:** Skip for now (the `astrodashctl ci up` test step will be removed temporarily)
- **Auto-deploy:** No. Image tag in the GitOps repo `values.yaml` will be updated manually
- **Paths filter:** Remove or update the `paths:` filter since it may prevent the workflow from running on tag pushes

## Resolved Questions

- **GitHub secrets needed:** `GITLAB_REGISTRY_USER` (set to `gitlab+deploy-token-12722131`) and `GITLAB_REGISTRY_TOKEN` (set to the deploy token value). These must be added to the GitHub repo's Settings > Secrets.
- **Deploy token permissions:** The existing deploy token must have `read_registry` and `write_registry` scopes. Verify this in GitLab project settings.
