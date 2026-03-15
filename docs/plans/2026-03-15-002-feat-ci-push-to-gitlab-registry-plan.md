---
title: "feat: Update CI to Push Images to GitLab Container Registry"
type: feat
status: active
date: 2026-03-15
origin: docs/brainstorms/2026-03-15-ci-image-push-to-gitlab-registry-brainstorm.md
---

# feat: Update CI to Push Images to GitLab Container Registry

Update `docker_image_workflow.yml` to build and push Docker images to `registry.gitlab.com/ncsa-caps-rse/astrodash-k8s-gitops`.

## Acceptance Criteria

- [x] Workflow logs in to GitLab Container Registry using deploy token
- [x] Image tagged with full registry path (`registry.gitlab.com/ncsa-caps-rse/astrodash-k8s-gitops:tag`)
- [x] `v*` tags produce `:version` + `:latest`; `dev*` tags produce `:version` + `:dev`
- [ ] GitHub secrets `GITLAB_REGISTRY_USER` and `GITLAB_REGISTRY_TOKEN` configured in repo settings
- [ ] Workflow pushes successfully on tag creation

## MVP

### .github/workflows/docker_image_workflow.yml

Changes needed:
1. Add `docker/login-action` step before the push step
2. Update `DOCKER_IMAGE` to include full registry path
3. Remove the test step (temporarily)
4. Remove or fix the `paths:` filter (it can prevent tag-triggered runs)
5. Use `set-output` replacement (`$GITHUB_OUTPUT`) since `::set-output` is deprecated

```yaml
name: Publish Docker image

on:
  push:
    tags:
      - "v[0-9]+.[0-9]+.[0-9]+"
      - "dev[0-9]-v[0-9]+.[0-9]+.[0-9]+"

jobs:
  build_push:
    runs-on: ubuntu-latest
    steps:
      - name: Free Disk Space (Ubuntu)
        uses: jlumbroso/free-disk-space@main
        with:
          tool-cache: false
          large-packages: true
          docker-images: false
          swap-storage: true

      - name: Checkout
        uses: actions/checkout@v6

      - name: Prepare tags
        id: prep
        run: |
          DOCKER_IMAGE=registry.gitlab.com/ncsa-caps-rse/astrodash-k8s-gitops
          if [[ $GITHUB_REF == refs/tags/v* ]]; then
            VERSION=${GITHUB_REF#refs/tags/}
            TAGS="${DOCKER_IMAGE}:${VERSION},${DOCKER_IMAGE}:latest"
          elif [[ $GITHUB_REF == refs/tags/dev* ]]; then
            VERSION=${GITHUB_REF#refs/tags/}
            TAGS="${DOCKER_IMAGE}:${VERSION},${DOCKER_IMAGE}:dev"
          fi
          echo "tags=${TAGS}" >> $GITHUB_OUTPUT

      - name: Set up Docker Buildx
        uses: docker/setup-buildx-action@v3

      - name: Log in to GitLab Container Registry
        uses: docker/login-action@v3
        with:
          registry: registry.gitlab.com
          username: ${{ secrets.GITLAB_REGISTRY_USER }}
          password: ${{ secrets.GITLAB_REGISTRY_TOKEN }}

      - name: Build and push
        uses: docker/build-push-action@v6
        with:
          context: ./app
          file: ./app/Dockerfile
          tags: ${{ steps.prep.outputs.tags }}
          cache-from: type=gha
          cache-to: type=gha,mode=max
          platforms: linux/amd64
          push: true
```

### GitHub repo settings

Add these secrets in the GitHub repo Settings > Secrets and variables > Actions:
- `GITLAB_REGISTRY_USER`: `gitlab+deploy-token-12722131`
- `GITLAB_REGISTRY_TOKEN`: the deploy token value

## Sources

- **Origin brainstorm:** [docs/brainstorms/2026-03-15-ci-image-push-to-gitlab-registry-brainstorm.md](docs/brainstorms/2026-03-15-ci-image-push-to-gitlab-registry-brainstorm.md)
- **Current workflow:** `.github/workflows/docker_image_workflow.yml`
- **GitOps repo:** `gitlab.com/ncsa-caps-rse/astrodash-k8s-gitops`
