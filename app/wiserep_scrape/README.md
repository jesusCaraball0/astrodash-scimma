# WISeREP monthly scrape

Offline operator tooling. It pulls the public supernova spectra WISeREP
ingested in a date window and writes them as a monthly challenge dataset.
Nothing in the request path imports it; the web app never runs it.

## Running it

It needs the app's Python environment, so run it in the container:

```bash
docker compose <compose args> exec app_dev python wiserep_scrape/wiserep_monthly_scrape.py \
  --start 2026-07-01 \
  --end   2026-07-31 \
  --output /mnt/astrodash-data/wiserep_challenge/2026-07
```

The search uses spectrum Creation Date (UT), accepts WISeREP's zip-of-CSV
export as well as bare CSV and HTML, skips residual-0 duplicate uploads, and
is idempotent: a re-run lands on the same filenames and re-downloads nothing
unless `--overwrite` is given.

`--delay` defaults to one second between requests. This runs once a month, so
there is no reason to go faster.

## Where a dataset lives

On the external data mount, alongside every other dataset this project uses,
not in the repository:

```
{ASTRODASH_DATA_DIR}/wiserep_challenge/<YYYY-MM>/
    metadata.csv       iau,filename,type,redshift
    spectra/           the ASCII spectra metadata.csv names
```

`ASTRODASH_DATA_DIR` is `/mnt/astrodash-data` by default. The repo keeps
model weights, templates, line lists and twins artifacts there rather than in
git (see the project CLAUDE.md), and a monthly dataset that grows by one
directory forever belongs there for the same reason. `.gitignore` excludes
`app/wiserep_scrape/data/` so a local run cannot commit a dataset by accident.

To publish a month for other environments, upload it under `init/data/` and
regenerate the manifest, exactly as for any other data file:
`docs/admin/updating-data-files.md`.

## Identifying the client

Requests carry a plain descriptive `User-Agent`:

```
AstroDASH-WISeREP-Ingest/1.0 (+https://astrodash.scimma.org)
```

An earlier revision sent a TNS-style marker with `"tns_id":0`. TNS issues real
bot ids on registration and WISeREP is operated by the same group, so a marker
carrying a placeholder id claims a registration that does not exist. If
AstroDASH registers a bot id, pass it with `--user-agent` rather than editing
the default back to a marker literal.

Only public, unauthenticated pages are read. No credentials are involved.

## Relationship to the leaderboard

This produces the input the monthly model leaderboard scores against. The two
are decoupled: the leaderboard page reads its own committed score JSON, and
the scoring step takes a dataset directory without caring how it was
produced.

If the leaderboard lands, point its `CHALLENGE_DATA_ROOT` at the mount path
above; it currently resolves to `app/wiserep_scrape/data`, which this change
stops tracking.
