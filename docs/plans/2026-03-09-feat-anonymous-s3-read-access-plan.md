---
title: Allow Anonymous S3 Read Access for Data Initialization
type: feat
date: 2026-03-09
---

# Allow Anonymous S3 Read Access for Data Initialization

## Overview

Remove the credential requirement for downloading initialization data from the Jetstream S3 bucket. The bucket supports full anonymous read access (list, stat, download), so credentials should only be required for write operations.

## Problem Statement

Currently `initialize_data.py:60-64` checks for `ASTRODASH_S3_ACCESS_KEY_ID` and `ASTRODASH_S3_SECRET_ACCESS_KEY` and returns early with a warning if either is missing. This means first-time users must obtain and configure S3 credentials before they can run astrodash, even though the bucket is publicly readable.

## Proposed Solution

Remove the early-return credential check in `verify_data_integrity()`. The `ObjectStore` class already handles empty credentials correctly — the minio client treats empty `access_key`/`secret_key` as anonymous access.

## Implementation Steps

### Step 1: Remove credential gate in `initialize_data.py`

In `verify_data_integrity()`, remove lines 60-64:

```python
# REMOVE THIS BLOCK:
if not DATA_INIT_S3_CONF['aws_access_key_id'] or not DATA_INIT_S3_CONF['aws_secret_access_key']:
    logger.warning('S3 credentials not configured. Set ASTRODASH_S3_ACCESS_KEY_ID and '
                   'ASTRODASH_S3_SECRET_ACCESS_KEY to enable data downloads.')
    logger.warning('Skipping data download.')
    return
```

Replace with an info-level log when credentials are absent:

```python
if not DATA_INIT_S3_CONF['aws_access_key_id'] or not DATA_INIT_S3_CONF['aws_secret_access_key']:
    logger.info('S3 credentials not configured. Using anonymous access for read operations.')
```

Then proceed to initialize the `ObjectStore` and download as normal.

### Step 2: Test

- Start containers **without** S3 credentials configured
- Verify data downloads complete successfully
- Start containers **with** S3 credentials configured
- Verify data downloads still work
- Test `manifest` command without credentials

## Acceptance Criteria

- [x] Data initialization downloads succeed without S3 credentials
- [ ] Data initialization downloads still work with S3 credentials
- [x] Manifest generation attempts anonymous access (may fail gracefully if versioned listing requires auth)
- [x] Info log message indicates anonymous access when no credentials are present
- [x] No changes to `ObjectStore` class

## References

- Brainstorm: `docs/brainstorms/2026-03-09-anonymous-s3-read-access-brainstorm.md`
- `app/entrypoints/initialize_data.py:60-64` — credential gate to remove
- `app/astrodash/shared/object_store.py:42-48` — minio client already accepts empty credentials
