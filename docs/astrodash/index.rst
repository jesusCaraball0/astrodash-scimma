AstroDASH 2.0 API Documentation
================================

AstroDASH 2.0 is an API for supernovae spectra classification using machine learning models.

- **Fast and reliable classification** (DASH CNN, Transformer, user models)
- **Single and batch processing** with multiple file formats or SN names
- **Strong contracts** with versioned REST endpoints and thorough docs

.. toctree::
   :maxdepth: 2
   :caption: API Reference

   api/swagger
   api/intro
   api/architecture_overview
   api/errors
   api/security
   api/advanced_usage
   api/integration_examples
   api/troubleshooting
   api/data_formats

.. toctree::
   :maxdepth: 2
   :caption: Endpoints

   api/endpoints/health
   api/endpoints/process_spectrum
   api/endpoints/batch_process
   api/endpoints/analysis_options
   api/endpoints/template_spectrum
   api/endpoints/estimate_redshift
   api/endpoints/line_list
   api/endpoints/models

.. toctree::
   :maxdepth: 2
   :caption: Guides

   guides/getting_started
   guides/code_examples/python
   guides/contribute
