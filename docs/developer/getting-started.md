# Developer Getting Started

## Quick Start

```bash
# Start the full development environment
run/astrodashctl full_dev up

# View logs
run/astrodashctl full_dev logs

# Stop the environment
run/astrodashctl full_dev down
```

The application will be available at `http://localhost:4000/astrodash/`.

### Running Tests

```bash
run/astrodash.test.sh slim_dev
```

### Development Profiles

| Profile | Command | Description |
|---------|---------|-------------|
| `full_dev` | `run/astrodashctl full_dev up` | Web app, database, Redis cache, and nginx |
| `slim_dev` | `run/astrodashctl slim_dev up` | Web app and database only (no Redis cache) |

### Version string in the footer

On the `full_dev` and `slim_dev` profiles, `astrodashctl` runs `git describe --tags --always` on the host at up-time and exports the result as `APP_VERSION`. The Django app reads it and shows it in the page footer, in the `/healthz` payload, and in the startup log line emitted by `AstroDashConfig.ready()`. So the footer names the commit the stack was launched from — useful when running multiple worktrees or branches side by side.

The value is a snapshot at up-time, not live per request. A commit made after `astrodashctl full_dev up` doesn't refresh the footer until the next `up` (`docker compose restart app` alone does not re-interpolate compose vars). `--dirty` is intentionally omitted: the dev overlay bind-mounts `app/` into the container, so running code diverges from the snapshotted working tree the moment you edit after `up`, and a stale `-dirty` (or non-dirty) suffix would report false state.

To display a specific string instead — for example, when testing what a release tag will render:

```bash
APP_VERSION=v1.2.3 run/astrodashctl full_dev up
```

Non-dev profiles (`full_prod`, `slim_prod`, `ci`, `docs`) and running `docker compose up` directly (bypassing `astrodashctl`) fall back to the literal `local`. The operator-side counterpart — how the Helm chart sets `APP_VERSION` on the deployed pod from the image tag — is documented in `docs/operator-runbook.md`.
