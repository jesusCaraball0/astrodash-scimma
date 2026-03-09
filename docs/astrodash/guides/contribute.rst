Contribute
==========

Overview
--------

Thanks for your interest in contributing! This page highlights common contribution areas like adding a new ML classifier to the codebase.

If you run into anything unclear, please open an issue or a draft PR so we can help refine this guide.

Contribute a new ML classifier model
-------------------------------------

This section explains how to add a first-class model kind (e.g., like ``dash`` or ``transformer``). The goal is to make your model selectable in the UI and callable via the API, with consistent inputs/outputs. Adding a model with this method provides more flexibility for customizing preprocessing, orchestrating inference, and adding more functionality (like templates) than uploading a Torchscripted model via the endpoint.

Assumptions
~~~~~~~~~~~

- You have a trained model checkpoint compatible with PyTorch.
- You know the model's expected inputs (e.g., length-N flux array vs wavelength+flux(+redshift)) and output label space.
- You can define preprocessing to reproduce your training normalization/resampling.

Backend changes (FastAPI)
~~~~~~~~~~~~~~~~~~~~~~~~~

1) Register the new model type in the model factory

- File: ``prod_backend/app/infrastructure/ml/model_factory.py``
- Add a branch in ``ModelFactory.get_classifier(model_type, user_model_id)`` to return your new classifier when ``model_type == '<your_model>'``.

2) Implement the classifier

- Create: ``prod_backend/app/infrastructure/ml/classifiers/<your_model>_classifier.py``
- Inherit from ``BaseClassifier`` and implement:

  - Model loading from ``Settings`` (path + hyperparams)
  - ``.classify(spectrum)`` that accepts preprocessed arrays, runs inference on CPU/GPU, and returns a result consistent with existing models
  - Label mapping (transform logits -> class names) if needed, similar to ``TransformerClassifier``

- If you need a custom architecture, add it under ``prod_backend/app/infrastructure/ml/classifiers/architectures.py`` (or a sibling module) and instantiate it in your classifier.

3) Add preprocessing (if needed)

- File: ``prod_backend/app/infrastructure/ml/data_processor.py``
- Pattern after ``DashSpectrumProcessor`` or ``TransformerSpectrumProcessor``. Ensure the logic mirrors training (interpolation, normalization, shaping).
- Update: ``prod_backend/app/domain/services/spectrum_processing_service.py``

  - Extend ``prepare_for_model(self, spectrum, model_type)`` with a new ``elif model_type == '<your_model>'`` branch returning exactly the tensors your classifier expects.

4) Template/redshift support (optional)

- If your model uses templates (for RLAP or redshift estimation), add a handler under ``prod_backend/app/infrastructure/ml/templates/`` and wire it in ``prod_backend/app/infrastructure/ml/templates/template_factory.py``.
- If not supported, keep DASH-only behavior intact. Redshift estimation endpoints purposely guard on ``model_type == 'dash'``.

5) API validation and routing

- Files to update (expand allowed values to include your type):

  - ``prod_backend/app/api/v1/spectrum.py`` (search for ``model_type not in ['dash', 'transformer']``)
  - ``prod_backend/app/api/v1/batch.py`` (same check)

- If your model requires extra inputs (e.g., mandatory redshift), add validation and clear error messages here.

6) Configuration

- File: ``prod_backend/app/config/settings.py``

  - Add env-backed fields for your model path and hyperparameters, e.g. ``YOURMODEL_MODEL_PATH``, dims, layers, dropout, etc.
  - For label mapping (class index -> label), follow the ``TransformerClassifier`` pattern.

7) Scripts (recommended)

- ``prod_backend/scripts/setup_data_directories.sh``

  - Create ``/data/pre_trained_models/<your_model>`` and export ``YOURMODEL_MODEL_PATH`` example.

- ``prod_backend/scripts/migrate_to_external_storage.sh``

  - Copy/move your pretrained checkpoint(s) into the above directory.

8) Tests

- Unit tests:

  - Extend ``prod_backend/tests/unit/test_classification_service.py`` to call the service with your ``model_type`` and assert behavior.
  - If you add a new processor, test its core transformations.

- Integration (optional but helpful):

  - Mirror ``tests/integration/test_transformer_classifier_integration.py`` with your checkpoint to achieve a smoke run.

Frontend changes (React)
~~~~~~~~~~~~~~~~~~~~~~~~~

1) Types and API client

- ``frontend/src/services/api.ts``

  - Update ``modelType?: 'dash' | 'transformer'`` to include your new type.

- ``frontend/src/components/ModelSelectionDialog.tsx``

  - Update ``export type ModelType = 'dash' | 'transformer' | { user: string };`` to include your new type string.

2) Selection UI

- Add a selectable card/button in ``ModelSelectionDialog.tsx`` that calls ``handleModelSelect('<your_model>')``.

3) Form behavior and validation

- Update logic that branches on ``'dash'`` vs ``'transformer'`` to also consider your type, in:

  - ``frontend/src/components/SupernovaClassifier.tsx``
  - ``frontend/src/components/BatchPage.tsx``

- Decide whether your model requires known redshift (Transformer currently does in the UI) and gate inputs accordingly.
- Keep RLAP/template UI only for DASH unless you explicitly add template support for your model.

4) Results display

- Ensure conditional rendering matches your outputs (e.g., hide RLAP if not produced). Keep the result shape consistent with the backend.

Documentation updates
~~~~~~~~~~~~~~~~~~~~~

- Add your model type to the accepted values in:

  - ``astrodash-docs/docs/api/intro.md``
  - ``astrodash-docs/docs/api/architecture-overview.md``
  - Endpoint docs that mention ``model_type`` (e.g., ``docs/api/endpoints/process-spectrum.md``, ``docs/guides/getting-started.md``)

- If your model doesn't support templates/redshift, note that those features remain DASH-only.

Checklist
~~~~~~~~~

- Backend

  - ``ModelFactory`` updated and classifier implemented
  - Preprocessor and ``prepare_for_model`` updated
  - Settings and env variables added
  - API validation extended for new type

- Frontend

  - Types widened and model selectable in UI
  - Form gating/validation updated
  - Result view aligns with outputs

- Docs & Tests

  - Docs list the new ``model_type``
  - Unit/integration tests added

- Ops

  - Model artifact present under ``/data/pre_trained_models/<your_model>/...``
  - Startup environment exports configured

Tips
~~~~

- Keep the backend response shape consistent across models to minimize frontend changes.
- Mirror your training preprocessing exactly; subtle differences in interpolation or normalization can degrade performance.
- Use ``torch.device('cuda' if available else 'cpu')`` and move tensors/models with ``.to(device)`` to support both CPU and GPU.

Add model-specific assets/templates for non-DASH models
--------------------------------------------------------

This section explains how to add the supporting assets ("templates" in a broad sense) required by models other than DASH -- for example, statistical normalization files, input-shape specs, lookup tables, or any auxiliary resources your model needs at inference time.

Overview
~~~~~~~~

Model assets are used for:

- **Preprocessing alignment**: Normalization stats, wavelength grids, or tokenizer/featurizer vocabularies
- **Output interpretation**: Label metadata
- **Optional lookups**: Any auxiliary tables used by your model during inference

Asset requirements
~~~~~~~~~~~~~~~~~~

1. **File structure**: Store assets alongside the model or under a clear subdirectory in ``/data/pre_trained_models/<your_model>/assets/`` (or with user models in ``/data/user_models/<model_id>/``).
2. **Configuration file**: Provide a small JSON/YAML that declares:

   - ``input_shapes``: list(s) of expected input shapes
   - ``preprocessing``: any required normalization parameters or grids
   - ``assets``: paths to auxiliary files the model will read at runtime

3. **Versioning**: Include an ``asset_version`` field and update it on changes.

Adding assets for a new or user-uploaded model
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Step 1: Prepare assets
^^^^^^^^^^^^^^^^^^^^^^

1. **Define inputs**: Document the exact inputs your model expects (e.g., wavelength/flux/redshift tensors, shapes).
2. **Normalization**: Export means/stds or other scalars/grids used by training.
3. **Aux files**: Include any lookup tables or tokenizers needed at inference.

Step 2: Place assets
^^^^^^^^^^^^^^^^^^^^

1. **Location**: Put assets under ``/data/user_models/<model_id>/assets/`` for user models, or ``/data/pre_trained_models/<your_model>/assets/`` for built-ins.
2. **Config**: Add an ``model_assets.json`` (or ``.yaml``) that references these files and declares shapes/mappings.

Step 3: Integration
^^^^^^^^^^^^^^^^^^^

1. **Loader**: Ensure the model loader reads your ``model_assets.json`` and wires preprocessing accordingly (e.g., in the classifier wrapper for that model type).
2. **Factory/registry**: If introducing a new built-in model type, register it in the model factory so the API can route requests properly.
3. **Validation**: On startup or upload, validate that shapes are consistent with the serialized model.

Validation and testing
~~~~~~~~~~~~~~~~~~~~~~

1. **Load test**: Confirm assets are discovered and parsed correctly.
2. **Shape test**: Verify dummy inputs shaped per ``input_shapes`` execute end-to-end.
3. **Repro test**: Run a known file and compare to expected outputs (tolerances as appropriate).

Best practices
~~~~~~~~~~~~~~

- **Single source of truth**: Keep shapes and normalization in one config that code loads.
- **Relative paths**: Use paths relative to the asset config for portability.
- **Schema stability**: Evolve the asset schema with explicit version bumps.
- **Document assumptions**: Note wavelength ranges, required units, or preprocessing expectations.
