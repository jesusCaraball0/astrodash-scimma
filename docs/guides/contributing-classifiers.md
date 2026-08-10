# Contributing a New ML Classifier

## Overview

Thanks for your interest in contributing! This page explains how to add a new ML classifier to the codebase.

If you run into anything unclear, please open an issue or a draft PR so we can help refine this guide.

## Contribute a New ML Classifier Model

This section explains how to add a first-class model kind (e.g., like `dash` or `transformer`). The goal is to make your model selectable in the UI and callable via the API, with consistent inputs/outputs. Adding a model with this method provides more flexibility for customizing preprocessing, orchestrating inference, and adding more functionality (like templates) than uploading a Torchscripted model via the endpoint.

### Assumptions

- You have a trained model checkpoint compatible with PyTorch.
- You know the model's expected inputs (e.g., length-N flux array vs wavelength+flux(+redshift)) and output label space.
- You can define preprocessing to reproduce your training normalization/resampling.

### Backend Changes (Django)

#### 1. Register the model in the model registry

- Directory: `app/astrodash/infrastructure/ml/model_registry/`
- Create `definitions/<your_model>.py` defining a `ModelDefinition`: its `id` is the `model_type`, plus its UI card fields (title, description, color, feature tags, icon, recommended), lifecycle `status`, `is_default`, the capability/requirement flags (`requires_redshift`, `preprocessing`, `supports_twins`, `supports_redshift_estimation`, `supports_template_overlays`, `supports_rlap`), and a reference to your classifier class (see step 2). Copy `definitions/dash.py` or `definitions/transformer.py` as a template.
- Add your definition to the ordered `MODELS` roster in `model_registry/__init__.py`.
- You do **not** edit `model_factory.py`. `ModelFactory.get_classifier` resolves the definition through the registry (`get_definition(model_type).classifier(config)`), so registering the definition is enough for the factory to build your classifier. The forms, the model-selection cards, and the behavioral gates likewise read from the definition. Exactly one active definition may be the default; the registry's import-time invariant check enforces this.

#### 2. Implement the classifier

- Create: `app/astrodash/infrastructure/ml/classifiers/<your_model>_classifier.py`
- Inherit from `BaseClassifier` and implement:
  - Model loading from `Settings` (path + hyperparams)
  - `.classify(spectrum)` that accepts preprocessed arrays, runs inference on CPU/GPU, and returns a result consistent with existing models
  - Label mapping (transform logits -> class names) if needed, similar to `TransformerClassifier`

- If you need a custom architecture, add it under `app/astrodash/infrastructure/ml/classifiers/architectures.py` (or a sibling module) and instantiate it in your classifier.

#### 3. Add preprocessing (if needed)

- File: `app/astrodash/infrastructure/ml/data_processor.py`
- Pattern after `DashSpectrumProcessor` or `TransformerSpectrumProcessor`. Ensure the logic mirrors training (interpolation, normalization, shaping).
- Update: `app/astrodash/domain/services/spectrum_processing_service.py`
  - Set your definition's `preprocessing` identifier, then extend `prepare_for_model(self, spectrum, model_type)` with a matching `elif preprocessing == '<your_variant>'` branch returning exactly the tensors your classifier expects. `prepare_for_model` reads the variant from your definition (`get_definition(model_type).preprocessing`), so it keys on that identifier rather than a raw `model_type` literal.

#### 4. Template/redshift support (optional)

- If your model uses templates (for RLAP or redshift estimation), add a handler under `app/astrodash/infrastructure/ml/templates/` and wire it in `app/astrodash/infrastructure/ml/templates/template_factory.py`.
- If not supported, leave the capability flags off. The redshift-estimation, twins, template-overlay, and RLAP gates read the definition's `supports_*` flags (e.g. `supports_redshift_estimation`), so a model with those flags `False` is excluded automatically — there is no per-model `model_type == 'dash'` branch to update.

#### 5. API validation and routing

- No allowed-list to widen. The REST endpoints in `app/astrodash/views.py` (`process_spectrum` and `batch_process`) resolve `modelType` through the registry via `_resolve_model_type`: any **active** definition is accepted automatically, and an omitted, unknown, or retired `modelType` returns `400`. Registering your definition with an active `status` is all the API needs to route to it.
- Extra-input requirements travel on the definition too. Set `requires_redshift=True` and the classify form and batch view enforce it from the flag; you do not add a bespoke validation branch.

#### 6. Configuration

- File: `app/astrodash/config/settings.py`
  - Add env-backed fields for your model path and hyperparameters, e.g. `YOURMODEL_MODEL_PATH`, dims, layers, dropout, etc.
  - For label mapping (class index -> label), follow the `TransformerClassifier` pattern.

#### 7. Tests

- Unit tests:
  - Extend classification service tests to call the service with your `model_type` and assert behavior.
  - If you add a new processor, test its core transformations.

- Integration (optional but helpful):
  - Mirror existing classifier integration tests with your checkpoint to achieve a smoke run.

### Frontend Changes (Django Templates)

The AstroDash frontend uses Django templates with Bootstrap, and the model-selection surface is now registry-driven — you do not hand-edit the template to add a card:

1. The model-selection cards render from the registry's active definitions (title, description, color, feature tags, icon, recommended badge, order), so setting your definition's UI fields adds the card. The form choice lists are generated the same way.
2. Redshift gating follows your `requires_redshift` flag; RLAP and template-overlay UI follow `supports_rlap` and `supports_template_overlays`. Set the flags rather than adding `'dash'` vs `'transformer'` branches in the template or form.
3. Ensure the result display matches your outputs (e.g., a model with `supports_rlap=False` produces no RLAP values to show).

### Documentation Updates

- Add your model type to the accepted values in:
  - `docs/api/introduction.md`
  - `docs/api/architecture.md`
  - Endpoint docs that mention `model_type` (e.g., `docs/api/endpoints/process-spectrum.md`, `docs/guides/getting-started.md`)

- If your model doesn't support templates/redshift, note that those features remain DASH-only.

### Checklist

- Backend
  - Registry definition added (`definitions/<id>.py` + `MODELS` entry) and classifier implemented
  - Preprocessor and `prepare_for_model` updated
  - Settings and env variables added
  - Capability/requirement flags set on the definition (API validation and gates derive from them)

- Frontend
  - Definition UI fields set (card renders from the registry)
  - Capability/requirement flags set (gating derives from them)
  - Result view aligns with outputs

- Docs & Tests
  - Docs list the new `model_type`
  - Unit/integration tests added

- Ops
  - Model artifact present under `/data/pre_trained_models/<your_model>/...`
  - Startup environment exports configured

### Tips

- Keep the backend response shape consistent across models to minimize frontend changes.
- Mirror your training preprocessing exactly; subtle differences in interpolation or normalization can degrade performance.
- Use `torch.device('cuda' if available else 'cpu')` and move tensors/models with `.to(device)` to support both CPU and GPU.

## Add Model-Specific Assets/Templates

This section explains how to add the supporting assets required by models other than DASH — for example, statistical normalization files, input-shape specs, lookup tables, or any auxiliary resources your model needs at inference time.

### Overview

Model assets are used for:

- **Preprocessing alignment**: Normalization stats, wavelength grids, or tokenizer/featurizer vocabularies
- **Output interpretation**: Label metadata
- **Optional lookups**: Any auxiliary tables used by your model during inference

### Asset Requirements

1. **File structure**: Store assets alongside the model or under a clear subdirectory in `/data/pre_trained_models/<your_model>/assets/` (or with user models in `/data/user_models/<model_id>/`).
2. **Configuration file**: Provide a small JSON/YAML that declares:
   - `input_shapes`: list(s) of expected input shapes
   - `preprocessing`: any required normalization parameters or grids
   - `assets`: paths to auxiliary files the model will read at runtime

3. **Versioning**: Include an `asset_version` field and update it on changes.

### Adding Assets

**Step 1: Prepare assets**

1. **Define inputs**: Document the exact inputs your model expects (e.g., wavelength/flux/redshift tensors, shapes).
2. **Normalization**: Export means/stds or other scalars/grids used by training.
3. **Aux files**: Include any lookup tables or tokenizers needed at inference.

**Step 2: Place assets**

1. **Location**: Put assets under `/data/user_models/<model_id>/assets/` for user models, or `/data/pre_trained_models/<your_model>/assets/` for built-ins.
2. **Config**: Add a `model_assets.json` (or `.yaml`) that references these files and declares shapes/mappings.

**Step 3: Integration**

1. **Loader**: Ensure the model loader reads your `model_assets.json` and wires preprocessing accordingly.
2. **Factory/registry**: If introducing a new built-in model type, register it in the model registry (a `definitions/<id>.py` file plus a `MODELS` entry) so the API can route requests properly.
3. **Validation**: On startup or upload, validate that shapes are consistent with the serialized model.

### Validation and Testing

1. **Load test**: Confirm assets are discovered and parsed correctly.
2. **Shape test**: Verify dummy inputs shaped per `input_shapes` execute end-to-end.
3. **Repro test**: Run a known file and compare to expected outputs (tolerances as appropriate).

### Best Practices

- **Single source of truth**: Keep shapes and normalization in one config that code loads.
- **Relative paths**: Use paths relative to the asset config for portability.
- **Schema stability**: Evolve the asset schema with explicit version bumps.
- **Document assumptions**: Note wavelength ranges, required units, or preprocessing expectations.
