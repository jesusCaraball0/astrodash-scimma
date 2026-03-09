---
title: Anonymous S3 Read Access for Data Initialization
date: 2026-03-09
---

# Anonymous S3 Read Access for Data Initialization

## What We're Building

Allow the astrodash data initialization process to download pre-trained models and spectra from the Jetstream S3 bucket without requiring credentials. The bucket supports full anonymous read access (list, stat, download).

## Why This Approach

- The Jetstream bucket at `js2.jetstream-cloud.org:8001` allows anonymous reads
- The minio Python client already supports anonymous access when empty strings are passed for access_key/secret_key
- The `ObjectStore` class already passes empty strings by default — no changes needed there
- The only blocker is an explicit credential check in `initialize_data.py` that returns early when credentials are missing
- This makes first-time setup much easier — no need to obtain and configure S3 credentials just to run astrodash

## Key Decisions

- **Anonymous for reads, credentials for writes**: When credentials are configured, use them. When absent, proceed with anonymous access for read operations.
- **Manifest generation also tries anonymous**: `generate_file_manifest()` will attempt anonymous access — it fails gracefully if versioned listing requires authentication.
- **No changes to ObjectStore**: The class already handles empty credentials correctly.

## Open Questions

- None — the scope is clear and minimal.
