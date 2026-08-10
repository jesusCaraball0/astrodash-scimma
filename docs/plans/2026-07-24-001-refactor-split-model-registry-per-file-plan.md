---
title: Split Model Registry Into Per-File Definitions - Plan
type: refactor
date: 2026-07-24
topic: split-model-registry-per-file
artifact_contract: ce-unified-plan/v1
artifact_readiness: implementation-ready
product_contract_source: ce-brainstorm
execution: code
---

# Split Model Registry Into Per-File Definitions - Plan

## Goal Capsule

- **Objective:** Turn `model_registry.py` into a package where each built-in model's `ModelDefinition` lives in its own file, assembled by a central `MODELS` roster, so adding a model becomes "write a definition file and register it" — keeping the definitions out of one growing file as classifiers are added, and bundling the overdue guide correction. Pure code organization: zero behavior change.
- **Product authority:** Scott Koranda (maintainer).
- **Open blockers:** None product-side. This refactor builds directly on the classifier registry introduced in PR #1 (`refactor/classifier-model-registry`), which is not yet merged to `main` — the module it reorganizes does not exist on `main`. Whether this work stacks on that branch or waits for its merge is a sequencing choice for planning, not a product decision.

## Product Contract

### Summary

Reorganize the single `model_registry.py` module into a `model_registry/` package: the `ModelDefinition` value for each built-in model (DASH, Transformer) moves to its own per-model file, and the package root assembles them into the ordered `MODELS` roster and hosts the lookup helpers. Every existing import path, monkeypatch seam, and behavior stays identical; the contributor guide is corrected to describe the registry reality it currently misdescribes.

### Problem Frame

A collaborator reviewing the registry design noted that holding every model's definition in one module gets long as models are added, and suggested each model live in its own file so adding one is "make a file and register it."

Two things narrow that observation. First, the classifier implementations (`BaseClassifier` subclasses) already live in their own files under `classifiers/`, and the factory is already generic post-registry — it resolves `get_definition(model_type).classifier(config)` with no per-model branch, so a contributor never edits the factory. The only place where all models still sit together is the `MODELS` tuple in `model_registry.py`. Second, the immediate next step is adding DAEP/BERTIE and retiring Transformer, which is exactly when the "how to contribute a model" pattern gets set — and the `contributing-classifiers.md` guide is currently stale, still instructing contributors to add an `if/elif` factory branch and to widen a `model_type not in ['dash','transformer']` check that the registry work already removed. PR #1's generic factory already made adding a classifier "add a definition and register it," so this split does not create that pattern. Its incremental value now is narrower and concrete: it keeps the definitions from piling into one growing file during the add-classifier change, and it bundles the stale-guide correction — the separable, contributor-facing defect. The file-per-model layout itself is a cheap, low-reversal-cost organization choice, not a prerequisite the contribution pattern depends on.

### Key Decisions

- **Split now, as a standalone refactor.** (session-settled: user-directed — chosen over bundling the split with the later add-DAEP step and over deferring until a third model lands: set the contribution pattern immediately, at two models, in an isolated zero-behavior-change PR.)
- **Central, explicitly-assembled roster — not self-registration.** Per-model files hold definition *values*; the package root imports them and builds the ordered `MODELS`. (session-settled: user-approved — consistent with PR #1's registry decision to keep a legible central roster; a data-driven or self-registering registry remains a later runway.)
- **`MODELS` and the lookup helpers stay in the package root; only definition values move.** `get_definition`, `active_definitions`, `default_definition`, `validate_registry`, and the `MODELS` binding remain in `model_registry/__init__.py`. This preserves both the existing `from astrodash.infrastructure.ml.model_registry import ...` import paths and the `patch.object(model_registry, "MODELS", patched)` test seam that the parity and REST-contract tests depend on. If a helper resolved `MODELS` from a different namespace than the one tests patch, the retire-in-a-test pattern would silently break.
- **Guide rewrite scoped to registry-reality corrections.** (session-settled: user-approved — the "contribute a first-class model" path is corrected to match the registry and the per-file structure; the unrelated model-assets half and ops content are left as-is.)

### Requirements

**Packaging and structure**

- R1. `model_registry.py` becomes a `model_registry/` package. Each built-in model's `ModelDefinition` value (DASH and Transformer) is defined in its own per-model file; the package root imports those definitions and binds the ordered `MODELS` roster from them, preserving today's order (Transformer first, then DASH).
- R2. The `ModelDefinition` dataclass, the `STATUS_ACTIVE` / `STATUS_RETIRED` constants, the `MODELS` binding, and the lookup helpers (`get_definition`, `active_definitions`, `default_definition`, `validate_registry`) remain importable from `astrodash.infrastructure.ml.model_registry` with unchanged names and signatures.
- R3. Adding a built-in model is localized to one new per-model definition file plus its registration in the central roster (an import and a `MODELS` entry). No edits to the factory, forms, templates, or behavioral gates are required — the property PR #1 established is preserved.

**Parity and compatibility**

- R4. Behavior is identical to today. DASH and Transformer are the active models, Transformer is the default, and every gate, card, label, and API contract behaves as before. No model is added or removed and no capability field changes.
- R5. The existing test suite passes unchanged. In particular, `patch.object(model_registry, "MODELS", ...)` still redirects the helpers (the retire-in-a-test pattern in `test_model_registry.py` and `test_api_model_type.py`), and importing the package still runs the registry invariant check that raises when the exactly-one-active-default rule is violated. A test pins the observable roster order (Transformer then DASH), since R1 makes that order a hand-maintained value rather than something the module structure enforces.
- R6. No existing import site changes. `model_factory.py`, `forms.py`, `ui_views.py`, the services, and all tests keep their current `model_registry` imports verbatim.

**Contributor guide**

- R7. `docs/guides/contributing-classifiers.md` is corrected so its "contribute a first-class model" path matches reality: registering a model is adding a per-model definition file plus its roster entry, not adding a factory `if/elif` branch; and the stale API-validation instruction (`model_type not in ['dash','transformer']`) and any now-inaccurate frontend-editing steps are updated to reflect the registry-driven cards, gates, and API contract.

### Acceptance Examples

- AE1. **Covers R2, R6.** **Given** the package refactor, **when** any current read site imports `get_definition`, `ModelDefinition`, `STATUS_ACTIVE`, `active_definitions`, or `default_definition` from `astrodash.infrastructure.ml.model_registry`, **then** the import resolves exactly as before.
- AE2. **Covers R5.** **Given** a test that does `patch.object(model_registry, "MODELS", patched)` with Transformer marked retired, **when** it calls `active_definitions()` and `get_definition("transformer")`, **then** Transformer is absent from the active set but still resolves its label and fields — identical to the pre-split behavior.
- AE3. **Covers R5.** **Given** a definition set that violates the exactly-one-active-default invariant, **when** the package is imported, **then** import fails with the same `ValueError` as today, because the invariant check still runs at package import.
- AE4. **Covers R3.** **Given** a hypothetical third model, **when** a contributor adds its definition file and registers it in the roster, **then** it appears on the selection surfaces and routes through the factory with no edits to the factory, forms, templates, or gates.
- AE5. **Covers R1, R4.** **Given** the assembled package, **when** `active_definitions()` and the rendered selection cards are read, **then** the order is Transformer then DASH, identical to today, and a test pins that order so the hand-assembled roster cannot silently drift.

### Scope Boundaries

- No behavior change, no capability-field change, and no edits to the classifier implementation files under `classifiers/`.
- `config/settings.py` is untouched; model paths and hyperparameters stay in the pydantic settings.
- The commented-out upload / user-model cards stay commented; the `user_model_id` factory bypass is unchanged.
- No self-registering or data-driven registry — still a deliberately-deferred later runway.
- No new model added and Transformer not retired; those remain separate later steps.
- The guide edit does not extend to the unrelated "model assets" section or ops content beyond correcting registry-driven inaccuracies.

### Outstanding Questions

**Resolved in planning (now Key Technical Decisions):**

- Package layout and the import-cycle break — settled as the `model_registry/` package with an internal `_model_definition.py` and a `definitions/` subpackage (KTD1).
- Naming of the per-model definition constants — settled as `DASH` / `TRANSFORMER` (KTD2).

**Deferred to the add-model step (recorded, not blocking):**

- Whether this refactor stacks on the open `refactor/classifier-model-registry` branch or lands after its merge.

### Sources / Research

- `app/astrodash/infrastructure/ml/model_registry.py` (PR #1 branch) — the module being reorganized: `ModelDefinition`, the `MODELS` tuple, the helpers, and the import-time `validate_registry(MODELS)` call.
- `app/astrodash/infrastructure/ml/model_factory.py` (PR #1 branch) — already generic; resolves `get_definition(model_type).classifier(config)` with no per-model branch.
- `app/astrodash/tests/test_model_registry.py`, `app/astrodash/tests/test_api_model_type.py` — use `patch.object(model_registry, "MODELS", ...)`; the seam R5 must preserve.
- `app/astrodash/tests/test_no_model_type_literals.py` — allowlist-scoped to four gate files and matches only comparison patterns, so it does not scan the registry and is unaffected by the split (verified, not assumed).
- `docs/guides/contributing-classifiers.md` — the stale guide R7 corrects.

---

## Planning Contract

**Product Contract preservation:** unchanged. Planning added HOW detail (package structure, execution sequencing, guide edits) and resolved the two deferred layout questions into KTD1/KTD2; no requirement, acceptance example, or scope boundary was rewritten.

**Target branch note:** the module this reorganizes exists only on `refactor/classifier-model-registry` (PR #1), not on `main`. All paths below assume that branch's state. Whether the work stacks on that branch or lands after its merge is a sequencing choice (see Risks & Dependencies), not a code decision.

### Key Technical Decisions

- KTD1. **`model_registry/` package with an internal `_model_definition.py` and a `definitions/` subpackage.** `_model_definition.py` holds the `ModelDefinition` dataclass and the `STATUS_ACTIVE` / `STATUS_RETIRED` constants; `definitions/dash.py` and `definitions/transformer.py` each hold one definition value; `__init__.py` re-exports the dataclass and constants, imports the definitions, binds `MODELS`, hosts the helpers, and runs the import-time invariant check. (session-settled: user-approved — chosen over a flat layout and over keeping the dataclass in `__init__`: the dedicated internal module is what lets per-model files import `ModelDefinition` without a cycle against the package root, and the subpackage keeps data files separate from machinery as models grow.)
- KTD2. **Per-model definition constants are named `DASH` and `TRANSFORMER`.** Each `definitions/<id>.py` exposes its definition under the uppercased model id; `__init__.py` imports them by that name. (Low-stakes naming pick resolved from the deferred question; the module path already namespaces them.)
- KTD3. **`MODELS`, the four helpers, and the import-time `validate_registry(MODELS)` call stay in `__init__.py`.** Instantiates the Product Contract Key Decision on the monkeypatch seam: the helpers must resolve `MODELS` from the same namespace tests patch (`model_registry.MODELS`), and `patch.object(model_registry, "MODELS", ...)` targets the package `__init__`. No helper moves into a submodule or a per-model file.
- KTD4. **Roster order is already pinned; the restructure keeps that oracle green.** The order (`transformer`, then `dash`) becomes a hand-maintained value in `__init__.py` after the split, but existing tests already assert it: `RegistryOrderingTests.test_active_definitions_are_transformer_then_dash` and `test_default_is_transformer` in `test_model_registry.py`, plus the card-order assertion in `test_classifier_parity.py`. So no new order coverage is added — the restructure must keep those assertions green, which is what makes the order-parity claim checked rather than asserted. (Corrects an earlier doc-review assumption that the order was unpinned; verified against the branch.)
- KTD5. **Behavior-preserving, no read-site edits.** Every current importer (`model_factory.py`, `forms.py`, `ui_views.py`, `spectrum_processing_service.py`, `redshift_service.py`, and all tests) keeps its `model_registry` imports verbatim; the package `__init__` re-exports the same names. The `test_no_model_type_literals.py` guard is allowlist-scoped to four gate files and never scans the registry, so moving definition literals into `definitions/*.py` does not trip it (verified) — no guard change.
- KTD6. **Guide correction scoped to the registry-driven path.** Instantiates the settled guide-scope decision: only the "contribute a first-class model" backend/frontend steps that the registry made inaccurate are rewritten; the "model assets" half and ops content stay as-is.

### Assumptions

- The refactor is authored against `refactor/classifier-model-registry`; the current `classifiers/` package (`base.py` + per-classifier files + `__init__.py`) is the in-repo precedent for a per-implementation-file package under `infrastructure/ml/`.
- `ModelFactory.get_classifier` already reads `definition.classifier` generically; no factory change is in scope.

### Risks & Dependencies

- **Depends on PR #1 (`refactor/classifier-model-registry`), which is unmerged.** Every "unchanged from today" baseline is measured against that branch. If PR #1's registry shape changes before merge, revisit the moved surface. Sequencing (stack on the branch vs land after merge) is deferred to the add-model step and does not change the code.
- **Import-cycle risk** is fenced by KTD1: per-model files import only from `_model_definition.py` (a leaf module), never from the package root, so `__init__` importing the definitions cannot cycle.

---

## Output Structure

```text
app/astrodash/infrastructure/ml/model_registry/
  __init__.py           # re-exports ModelDefinition, STATUS_ACTIVE, STATUS_RETIRED;
                        #   imports DASH, TRANSFORMER; MODELS = (TRANSFORMER, DASH);
                        #   get_definition / active_definitions / default_definition /
                        #   validate_registry; validate_registry(MODELS) at import
  _model_definition.py  # ModelDefinition dataclass, STATUS_ACTIVE, STATUS_RETIRED,
                        #   is_active property
  definitions/
    __init__.py
    dash.py             # DASH = ModelDefinition(...)  (imports DashClassifier)
    transformer.py      # TRANSFORMER = ModelDefinition(...)  (imports TransformerClassifier)
```

The single file `app/astrodash/infrastructure/ml/model_registry.py` is removed; the package above replaces it. The per-unit `**Files:**` sections remain authoritative.

---

## Implementation Units

### U1. Restructure `model_registry.py` into the `model_registry/` package

- **Goal:** Move to the KTD1 package layout, preserving every import path, the monkeypatch seam, the import-time invariant, and all behavior. Roster order stays covered by the existing order tests (KTD4); no new order coverage is added.
- **Requirements:** R1, R2, R3, R4, R5, R6, AE1, AE2, AE3, AE4, AE5 (KTD1, KTD2, KTD3, KTD4, KTD5).
- **Dependencies:** none.
- **Files:** remove `app/astrodash/infrastructure/ml/model_registry.py`; create `app/astrodash/infrastructure/ml/model_registry/__init__.py`, `.../model_registry/_model_definition.py`, `.../model_registry/definitions/__init__.py`, `.../model_registry/definitions/dash.py`, `.../model_registry/definitions/transformer.py`. Touch no read-site file; `test_model_registry.py`, `test_model_factory.py`, `test_api_model_type.py`, `test_classifier_parity.py` should pass unedited.
- **Approach:** `_model_definition.py` gets the `ModelDefinition` dataclass, `STATUS_ACTIVE` / `STATUS_RETIRED`, and `is_active` verbatim. Each `definitions/<id>.py` imports `ModelDefinition` and the constants from `.._model_definition` and its classifier from `classifiers/`, and binds `DASH` / `TRANSFORMER` with today's exact field values. `__init__.py` re-exports `ModelDefinition`, `STATUS_ACTIVE`, `STATUS_RETIRED`; imports `TRANSFORMER` and `DASH`; binds `MODELS = (TRANSFORMER, DASH)`; defines `get_definition`, `active_definitions`, `default_definition`, `validate_registry` unchanged; and calls `validate_registry(MODELS)` at module end. Confirm `test_no_model_type_literals.py` is untouched and green (allowlist scope). The existing order oracle (`RegistryOrderingTests` in `test_model_registry.py`; the card-order assertion in `test_classifier_parity.py`) must stay green through the move; no order test is added.
- **Execution note:** Behavior-preserving; keep the full existing suite green throughout — the `RegistryOrderingTests` order/default assertions, the `test_classifier_parity` card-order assertion, the retire-in-a-test cases, and the invariant test are the parity oracle. No read-site edits — if one seems necessary, stop and surface it.
- **Patterns to follow:** `app/astrodash/infrastructure/ml/classifiers/` (a per-implementation-file package with `__init__.py`, `base.py`, and per-classifier modules).
- **Test scenarios:**
  - Covers AE1. Existing importers resolving `get_definition`, `ModelDefinition`, `STATUS_ACTIVE`, `active_definitions`, `default_definition` from `astrodash.infrastructure.ml.model_registry` still succeed (existing tests exercise these).
  - Covers AE2. `patch.object(model_registry, "MODELS", patched)` with Transformer retired still drops it from `active_definitions()` while `get_definition("transformer")` resolves (existing `test_model_registry.py` / `test_api_model_type.py` retire-in-a-test cases pass unedited).
  - Covers AE3. Importing the package with a two-active-default `MODELS` raises `ValueError` (the invariant test passes unedited).
  - Covers AE4 (indirect). The factory resolves `get_definition(model_type).classifier(config)` generically, so no factory edit is needed to add a model (existing `test_model_factory.py` dispatch + `user_model_id` bypass pass unedited); the "appears on the selection surfaces" half is structurally guaranteed by the registry-driven cards rather than directly tested, since no third model is added in this refactor.
  - Covers AE5. The existing `RegistryOrderingTests` order/default assertions and the `test_classifier_parity` card-order assertion stay green through the move.
- **Verification:** full suite green; a grep confirms no `from ...model_registry import` line in any read-site file changed.

### U2. Correct the contributor guide

- **Goal:** Bring `contributing-classifiers.md`'s "contribute a first-class model" path in line with the registry and the per-file structure.
- **Requirements:** R7 (KTD6).
- **Dependencies:** U1 (so the guide describes the actual new structure).
- **Files:** `docs/guides/contributing-classifiers.md`.
- **Approach:** Rewrite the backend "register in the model factory" step (currently "add an `if/elif` branch to `ModelFactory.get_classifier`") to "add a `model_registry/definitions/<id>.py` defining a `ModelDefinition` and register it in `MODELS`." Drop the stale API-validation instruction (`model_type not in ['dash', 'transformer']`) and describe the registry-driven validation plus the REST `modelType` contract. Update the frontend steps that tell contributors to hand-edit cards and gates to reflect that cards, form choices, and behavioral gates now derive from the definition. Leave the "Add Model-Specific Assets/Templates" half and ops/checklist content untouched except where they name the removed factory branch.
- **Execution note:** Documentation only. Test expectation: none — documentation change with no behavioral surface.
- **Test scenarios:** none (documentation).
- **Verification:** the guide's first-class-model path names the definition-file + `MODELS` registration and carries no lingering reference to a factory `if/elif` branch or the removed `model_type not in [...]` check.

---

## Verification Contract

- **Full suite:** run the container test command from `CLAUDE.md` (`docker exec <app service> python manage.py test astrodash.tests users.tests`, or `run/astrodash.test.sh slim_dev` when the project name matches). Must be green, including U1's order assertions and the unedited registry/factory/parity/guard tests.
- **Single module while iterating:** `... python manage.py test astrodash.tests.test_model_registry astrodash.tests.test_classifier_parity -v 2`.
- **Import-path check:** `python -c "from astrodash.infrastructure.ml.model_registry import ModelDefinition, MODELS, get_definition, active_definitions, default_definition, validate_registry, STATUS_ACTIVE, STATUS_RETIRED"` resolves with no error.
- **Formatting:** `black` over the changed Python files.
- **Manual parity check:** load `http://localhost:4000/astrodash/select-model/?action=classify` and confirm the cards render identically — Transformer then DASH (RECOMMENDED), upload cards absent.

---

## Definition of Done

- R1-R7 satisfied: the `model_registry/` package matches the Output Structure; the dataclass, constants, `MODELS`, and helpers import from `astrodash.infrastructure.ml.model_registry` unchanged (R2, R6, AE1); the `patch.object` retire seam works (AE2); the import-time invariant still raises (AE3); roster order stays pinned through the restructure by the existing order tests (R5, AE5); adding a model is a definition file plus a `MODELS` entry (R3, AE4).
- Zero behavior change: DASH and Transformer active, Transformer default, all gates/cards/labels/API contract identical; no capability field changed.
- The full suite plus coverage is green; the existing order, parity, retire, and invariant tests pass unchanged before and after the restructure; no read-site import changed; the `test_no_model_type_literals.py` guard is unedited and green.
- `contributing-classifiers.md`'s first-class-model path matches the new structure (R7); the model-assets half is untouched.
- `config/settings.py` and the `classifiers/` implementation files are untouched; upload/user-model cards stay commented.
- Changed Python is `black`-formatted.
