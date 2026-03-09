Welcome to the AstroDASH 2.0 API
=================================

AstroDASH 2.0 is an API for supernovae spectra classification using machine learning models.

- **Fast and reliable classification** (DASH CNN, Transformer, user models)
- **Single and batch processing** with multiple file formats or SN names
- **Strong contracts** with versioned REST endpoints and thorough docs

Explore the docs to get started, or jump to the :doc:`Interactive API Explorer <swagger>`. The v1 API lives under the ``/api/v1`` prefix.

----

Purpose
-------

AstroDash serves astronomers, astrophysicists, machine learning researchers, and tool builders who need robust, reproducible classification of supernova spectra and related analysis. The API is optimized for interactive web apps and automated pipelines alike.

Base URL and Versioning
-----------------------

- Base URL (local): ``http://localhost:8000`` (NEEDS update)
- API prefix: ``/api/v1``
- Versioning policy: breaking changes are introduced only in new major versions (e.g., ``/api/v2``). Backward-compatible changes can ship in minor versions.

Quick Start
-----------

1) Health check: ``GET /health``
2) Classify one spectrum: ``POST /api/v1/process`` with ``file`` (or ``params.oscRef``)
3) Explore and test endpoints: Swagger UI at ``/docs``, OpenAPI at ``/openapi.json``

API Surface Summary
-------------------

- **Spectrum and Classification**

  - ``POST /api/v1/process``: classify a single spectrum (file or OSC reference)

- **Batch**

  - ``POST /api/v1/batch-process``: classify a ZIP folder or multiple files

- **Templates**

  - ``GET /api/v1/analysis-options``: list valid SN types and age bins for DASH
  - ``GET /api/v1/template-spectrum``: return a DASH template spectrum (``x``, ``y``)

- **Line Lists**

  - ``GET /api/v1/line-list[...]``: Get a list of single element or compound wavelength markers

- **User Models**

  - ``POST /api/v1/upload-model``: upload TorchScript model with metadata
  - ``GET/PUT/DELETE /api/v1/models/...``: manage models

- **Redshift**

  - ``POST /api/v1/estimate-redshift``: estimate redshift (using DASH templates). More ways of estimating coming soon.

Next Steps
----------

- :doc:`Getting Started Guide </astrodash/guides/getting_started>`
- :doc:`Architecture Overview <architecture_overview>`
- :doc:`Error Model <errors>`
- :doc:`API Endpoints Reference <endpoints/health>`
- :doc:`Code Examples </astrodash/guides/code_examples/python>`
- :doc:`Interactive API Explorer <swagger>`
