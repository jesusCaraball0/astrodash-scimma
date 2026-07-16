---
artifact_contract: ce-unified-plan/v1
artifact_readiness: implementation-ready
execution: code
product_contract_source: ce-brainstorm
type: refactor
date: 2026-07-15
---

# REST Model-Registry Contract - Plan

## Goal Capsule

- **Objective:** Close the gap between the classifier model registry and the REST API so that adding or removing a model from the registry is reflected in the API's accepted `modelType` values, with no edits to the endpoint code.
- **Product authority:** This ce-brainstorm session. The registry itself (DASH, Transformer described once in `app/astrodash/infrastructure/ml/model_registry.py`) was shipped in PR #1; this is the deferred REST-layer follow-up, a separate PR.
- **Open blockers:** None. All contract decisions are settled below.

## Product Contract

### Summary

The UI/service layer now derives every model read site from the registry, but the REST layer (`app/astrodash/views.py`) still hardcodes model handling: the classify and batch endpoints carry an identical `modelType` guard with a literal allowed-set and a literal `"dash"` default. Add a model to the registry and the API silently rejects it; retire one and the API keeps accepting it. This work routes the two endpoints' `modelType` validation through the registry so the registry is the single source of truth for the API too, and tightens the contract: `modelType` is required (no implicit default) and an unknown or retired value returns `400` instead of being silently coerced to `"dash"`.

### Problem Frame

- **Who:** Internal, access-controlled consumers only -- internal scripts and access-gated programmatic clients. The AstroDash web UI is **not** a consumer of these REST endpoints: it invokes the domain services directly (`get_classification_service`, `get_batch_processing_service`), so `process_spectrum` / `batch_process` are not on the UI's request path. The public `astrodash.scimma.org` surface is access-controlled, so no external/public programmatic users are owed backward-compatibility, and the `400`-on-invalid and required-`modelType` changes are acceptable and coordinatable.
- **What's wrong:** `app/astrodash/views.py` repeats, in `process_spectrum` (classify, lines 161-163) and `batch_process` (lines 403-405):
  ```python
  model_type = "user_uploaded" if model_id else params.get("modelType", "dash")
  if model_type not in ("dash", "transformer", "user_uploaded"):
      model_type = "dash"
  ```
  The allowed-set and default are literals, disconnected from the registry. An unknown `modelType` is silently coerced to `"dash"` (a latent bug that hides client errors), and the API's omitted-default (`"dash"`) diverges from the registry/UI default (`"transformer"`).
- **Why now:** PR #1 made the registry the source of truth everywhere except here. Leaving the REST layer hardcoded means future add/remove work has to remember to hand-edit these endpoints, which is exactly the drift the registry was built to remove.

### Key Decisions

- **KD1. Internal, access-controlled clients; breaking changes are acceptable.** The `400` semantics and required-`modelType` behavior can change the current contract because all callers are internal and coordinatable: the public `astrodash.scimma.org` endpoint is access-gated, and the web UI calls the domain services directly rather than these endpoints. (session-settled: user-directed.)
- **KD2. `modelType` is required; the API keeps no implicit default.** When `model_id` is absent, an omitted `modelType` returns `400`. (session-settled: user-directed -- chosen over following the registry default `"transformer"` and over preserving the current `"dash"` default; leaves no default literal to drift.)
- **KD3. Unknown or retired `modelType` returns `400`.** Replaces today's silent coercion to `"dash"`, using the endpoints' existing `_json_error` convention. (session-settled: user-directed -- chosen over silent fallback and over still-serving a retired model.)
- **KD4. The registry is the single source of truth for the API.** The endpoints validate against `active_definitions()` / `get_definition()`; they do not maintain their own model list. (session-settled: user-approved -- extends PR #1's registry to the REST layer.)
- **KD5. No discovery endpoint now.** Exposing the active registry (ids + capabilities) to clients is deferred, not built. Internal clients know the ids and the UI renders models server-side. (session-settled: user-directed -- YAGNI given internal-only clients; recorded as a future option.)

### Requirements

- **R1.** The classify (`process_spectrum`) and batch (`batch_process`) endpoints validate the client-supplied `modelType` against the registry's active definitions. No hardcoded allowed-set tuple and no `"dash"` default literal remain in these endpoints.
- **R2.** When `model_id` is absent, `modelType` is required: an omitted (or empty) `modelType` returns `400`.
- **R3.** An unknown `modelType`, or one whose registry definition is retired (not active), returns `400` via the existing `_json_error` helper -- replacing the current silent coercion to `"dash"`.
- **R4.** When `model_id` is present, the user-uploaded path is unchanged: the request resolves to the user-uploaded model and `modelType` is not required.
- **R5.** Parity for valid requests: a request naming an active built-in (`dash`, or `transformer` while it is active) classifies exactly as it does today. The changed paths are: omitted `modelType`, unknown `modelType`, retired `modelType`, and the corner case of a client sending `modelType="user_uploaded"` without a `model_id` -- today's guard accepts that literal, the new rule returns `400` because `"user_uploaded"` is not a client-selectable built-in (it is derived from `model_id` presence, per R4).
- **R6.** The `estimate-redshift` endpoint is unchanged. It does not accept a client `modelType` (redshift estimation is DASH-only and the endpoint calls the service with a fixed `"dash"`), so it is outside this contract.
- **R7.** No model-discovery endpoint is added. Exposing the registry via the API is recorded as a future option, not built here.
- **R8.** The published API contract is updated to match the new behavior: `docs/api/openapi.json` and the relevant `docs/api/*` pages (e.g. `advanced-usage.md`, `endpoints/process-spectrum.md`, the batch endpoint) mark `modelType` as required when `model_id` is absent and document the `400` on unknown or retired `modelType`. The documented contract-of-record moves with the registry-driven behavior, rather than continuing to show `modelType` as optional (which would reintroduce, at the documentation layer, the drift KD4 exists to remove).

### Acceptance Examples

- **AE1. Covers R1, R2.** **Given** a classify request with no `model_id` and no `modelType`, **when** it is handled, **then** the API returns `400` with a clear "modelType is required" error, rather than defaulting to a model.
- **AE2. Covers R1, R3.** **Given** a classify request with `modelType="bogus"`, **when** it is handled, **then** the API returns `400`, rather than silently classifying with DASH.
- **AE3. Covers R1, R3 (registry as source of truth).** **Given** a model marked retired in the registry, **when** a classify request names that `modelType`, **then** the API returns `400` -- because only active definitions are accepted -- without any edit to the endpoint code.
- **AE4. Covers R1, R5.** **Given** a classify request with `modelType="transformer"` (active) and a redshift, **when** it is handled, **then** it classifies with Transformer exactly as today.
- **AE5. Covers R4.** **Given** a classify request with a valid `model_id`, **when** it is handled, **then** it runs the user-uploaded classification unchanged, regardless of `modelType`.

### Success Criteria

- **Registry-driven, demonstrated.** Adding a model to the registry makes the REST endpoints accept it, and retiring/removing one makes them reject it, with no edits to `views.py`. Shown by AE3 (retire-in-a-test) and by the absence of a hardcoded allowed-set or `"dash"` default in the classify/batch endpoints.
- **Contract tightened without regression.** Existing valid built-in and user-uploaded requests behave identically; the omitted/unknown/retired paths now return `400`. The existing API tests plus new ones covering AE1-AE5 are green.

### Scope Boundaries

**In scope:**
- The `modelType` validation and default handling in `process_spectrum` and `batch_process`.
- Updating the published API contract (`docs/api/openapi.json` and the affected `docs/api/*` pages) to match the new behavior (R8).

**Out of scope (deferred / non-goals):**
- A model-discovery endpoint or otherwise exposing the registry through the API (KD5) -- deferred, recorded as a future option.
- The `estimate-redshift` endpoint's fixed `"dash"` (R6) -- not client-driven.
- The registry design itself -- settled and shipped in PR #1.
- External/public API backward-compatibility handling -- not applicable; clients are internal (KD1).

### Outstanding Questions

**Deferred to planning:**
- Whether unknown vs retired `modelType` return distinct `400` messages or a single "not an available model" message.
- Whether the two endpoints' identical guard is extracted into a shared helper (e.g. a `resolve_model_type(params, model_id)` that raises a validation error), or inlined at each site.
- Whether `"user_uploaded"` remains an inline literal in the resolution logic or is also sourced from a shared constant.

**Deferred to the later add/remove steps (recorded, not blocking):**
- If/when an external client base appears, revisit KD1 -- retired-model `400` and required-`modelType` may then warrant a versioned or gentler contract, and the deferred discovery endpoint (KD5) may become worthwhile.

### Sources / Research

- `app/astrodash/views.py:161-163` (classify guard), `:403-405` (batch guard) -- the identical hardcoded allowed-set and `"dash"` default this work replaces.
- `app/astrodash/views.py:50` -- the `_json_error(message, status)` convention the `400` responses should use, already used for other validation failures in these endpoints.
- `app/astrodash/views.py` `estimate_redshift` (calls the service with fixed `model_type="dash"`; reads no client `modelType`) -- confirms R6 is out of scope.
- `app/astrodash/views.py` `analysis_options` -- returns template-analysis options, not model info; confirms no model-discovery surface exists today.
- `app/astrodash/infrastructure/ml/model_registry.py` -- `active_definitions()` and `get_definition()` (with the active/retired `status`), which the endpoint validation reads. Note: `default_definition()` (the registry's `transformer` default) is deliberately **not** used by the REST layer, per KD2 -- the API keeps no implicit default.
- `app/astrodash/ui_views.py` -- calls the domain services directly (`get_classification_service`, `get_batch_processing_service`); confirms the web UI is not a consumer of the `process_spectrum` / `batch_process` REST endpoints.
- `docs/api/openapi.json`, `docs/api/advanced-usage.md`, `docs/api/endpoints/process-spectrum.md` -- the published contract-of-record that currently documents `modelType` as optional (and shows `params='{}'` calls omitting it); R8 updates these to match.
- `app/astrodash_project/urls.py:13` -- the API is versioned at `astrodash/api/v1/`.
- `docs/plans/2026-07-15-001-refactor-classifier-model-registry-plan.md` and PR #1 -- the registry this work extends to the REST layer.

---

## Planning Contract

**Product Contract preservation:** unchanged. Planning added no new product scope; it enriches the same requirements (R1-R8) with implementation detail. The R8 docs requirement and the Problem Frame correction both landed during the requirements phase (ce-doc-review), not planning.

### Key Technical Decisions

- **KTD1. One shared resolver, not a duplicated guard.** Extract a single helper -- `_resolve_model_type(params, model_id)` in `app/astrodash/views.py` -- that both `process_spectrum` and `batch_process` call, replacing the identical hardcoded guard at both sites. It is the single place the registry lookup lives, so a registry change reaches both endpoints at once. (Instantiates KD4; also resolves the requirements-phase Outstanding Question about a shared helper.)
- **KTD2. Resolution rules, in order.** The resolver returns `"user_uploaded"` when `model_id` is truthy (unchanged from today, ahead of any registry lookup). Otherwise it reads `modelType` from `params`; missing or empty -> raise; present -> `get_definition(modelType)`; `None` (unknown) or not `is_active` (retired) -> raise. A resolved active built-in id is returned as-is. (Instantiates KD2, KD3, KD4; mirrors the factory precedence shipped in PR #1, where `user_model_id` is checked before the registry.)
- **KTD3. Errors raise `AppException` (400) and return via `_json_error`, with distinct messages.** The resolver raises `AppException(message, status_code=HTTP_400_BAD_REQUEST)` from `app/astrodash/core/exceptions.py` -- the base `AppException` accepts `status_code` (default `400`), and its `.message` / `.status_code` flow through the existing `_json_error(exc.message, status=exc.status_code)` convention. It deliberately does **not** use `ValidationException`, which hardcodes `422` and takes no `status_code` argument, so it cannot yield the `400` the contract (AE1-AE5) requires. Both endpoints already catch exceptions from `_parse_params`, but the modelType guard sits *after* that block, so each endpoint wraps the resolver call in its own `try/except AppException -> _json_error(exc.message, status=exc.status_code)` (consistent with `batch_process`, which already returns `_json_error(..., status=400)` for its own validations). Three distinct `400` messages: omitted -> "modelType is required."; unknown -> "Unknown model type: `<value>`."; retired -> "Model type `<value>` is not available." (Resolves the requirements-phase Outstanding Question about distinct vs single messages.)
- **KTD4. The API keeps no default; `default_definition()` is not called here.** The resolver never falls back to a default model -- omitting `modelType` is an error, not a silent default. `default_definition()` (the registry's `transformer` default) is deliberately not referenced by the REST layer. (Instantiates KD2.)
- **KTD5. `"user_uploaded"` stays an inline literal in the resolver.** It is not routed through the registry (it has no `ModelDefinition`) and is low-churn, so a shared constant is not warranted. (Resolves the requirements-phase Outstanding Question; the guard against re-introducing built-in literals lives in PR #1's scope, not this one.)
- **KTD6. Tests assert the new contract, not the old behavior.** Unlike PR #1 (a behavior-preserving refactor pinned by characterization tests), this is a deliberate behavior change on the omitted/unknown/retired/`user_uploaded`-without-`model_id` paths. The new tests assert the new `400` contract (test-first: these fail on today's silent-coerce code) plus parity tests for the unchanged paths (a valid built-in classifies; `model_id` present routes to user-uploaded). (Instantiates KD1-KD3.)

### Assumptions

- The classify/batch endpoints can be driven in a test with the classification/batch services mocked, so parity tests need no model weights (the same technique PR #1's view-gate tests used).

---

## Implementation Units

### U1. Route the classify and batch endpoints' modelType through the registry

- **Goal:** Replace the hardcoded allowed-set/default guard in both REST endpoints with a shared registry-driven resolver that requires `modelType` and returns `400` for omitted, unknown, or retired values, while preserving the `model_id` -> user-uploaded path and valid built-in classification.
- **Requirements:** R1, R2, R3, R4, R5 (KTD1-KTD6).
- **Dependencies:** none (the registry API it depends on shipped in PR #1).
- **Files:**
  - `app/astrodash/views.py` (add `_resolve_model_type` helper; wire `process_spectrum` and `batch_process` to it, removing the two hardcoded guards)
  - `app/astrodash/tests/test_api_model_type.py` (new)
- **Approach:** Add `_resolve_model_type(params, model_id)` per KTD2/KTD3, raising `AppException(message, status_code=HTTP_400_BAD_REQUEST)` on the invalid paths. In `process_spectrum` (lines 161-163) and `batch_process` (lines 403-405), replace the `model_type = ...; if model_type not in (...)` block with a call to the resolver wrapped in a `try/except AppException -> _json_error(exc.message, status=exc.status_code)`. Both endpoints already catch exceptions from `_parse_params`, but the modelType guard sits after that block, so the resolver call gets its own wrapper in each. Keep everything downstream of `model_type` unchanged. Import `get_definition` from `app/astrodash/infrastructure/ml/model_registry.py` and `AppException` (with `HTTP_400_BAD_REQUEST`) from `app/astrodash/core/exceptions.py`.
- **Execution note:** Write the new-contract tests first -- the omitted/unknown/retired/`user_uploaded`-without-`model_id` cases fail on today's silent-coerce code, which drives the change. Keep the parity tests (valid built-in, `model_id` path) green throughout.
- **Patterns to follow:** the registry usage and retire-in-a-test technique from PR #1 (`docs/plans/2026-07-15-001-...-plan.md`, its U2/U5 tests and `app/astrodash/tests/test_model_registry.py`); the `try/except ... : return _json_error(exc.message, status=exc.status_code)` blocks already around `_parse_params` in both endpoints (the resolver mirrors them, raising `AppException` at `400` rather than `ValidationException`'s `422`); service-mocked view tests as in `app/astrodash/tests/test_classifier_parity.py` (`ClassifyViewGateParityTests`).
- **Test scenarios** (in `test_api_model_type.py`; drive the endpoints via the Django test client, classification/batch services mocked):
  - Covers AE1. `POST` classify with no `model_id` and no `modelType` -> `400`, body message "modelType is required."; classification service not invoked.
  - Covers AE2. `POST` classify with `modelType="bogus"` -> `400`, "Unknown model type: bogus."; not silently classified as DASH.
  - Covers AE3. With the registry patched so `transformer` is retired (`unittest.mock.patch` on `model_registry.MODELS`, mirroring PR #1's AE5 test), `POST` classify with `modelType="transformer"` -> `400`, "Model type transformer is not available."
  - Covers AE4. `POST` classify with `modelType="transformer"` (active) and a valid `params` -> reaches the (mocked) classification service with `model_type="transformer"`; response is the normal success payload.
  - Covers AE5. `POST` classify with a valid `model_id` and any/omitted `modelType` -> resolves to `"user_uploaded"`, `modelType` ignored; user-uploaded path invoked unchanged.
  - `modelType="user_uploaded"` with no `model_id` -> `400` (not a client-selectable built-in), per R5.
  - Batch parity: repeat the omitted-`400`, unknown-`400`, retired-`400`, and valid-built-in-succeeds scenarios against the `batch_process` endpoint.
- **Verification:** the new `test_api_model_type.py` passes; the full suite (`run/astrodash.test.sh slim_dev`) stays green; `black` clean on `views.py` and the new test.

### U2. Update the published API contract to match

- **Goal:** Move the documented contract-of-record in step with the new behavior so internal consumers reading the docs no longer see `modelType` as optional.
- **Requirements:** R8 (KTD indirectly via KD4).
- **Dependencies:** U1 (docs describe the behavior U1 ships).
- **Files:**
  - `docs/api/openapi.json` (mark `modelType` required when `model_id` is absent; document the `400` response for unknown/retired/omitted `modelType`)
  - `docs/api/advanced-usage.md` (fix examples that post `params='{}'` / omit `modelType`)
  - `docs/api/endpoints/process-spectrum.md` (add `modelType` to the parameter table; note it is required without `model_id`; document the `400`)
  - the batch endpoint doc page under `docs/api/endpoints/` if one exists (same edits)
- **Approach:** Documentation-only. Keep the model ids referenced in examples (`dash`, `transformer`) consistent with the active registry; do not enumerate a hardcoded list the docs would have to chase on every registry change -- state that valid values are the active built-in model ids and, where an example is needed, use `dash`.
- **Test expectation:** none -- documentation only; no behavioral code changes. Verified by review against U1's contract.
- **Verification:** the openapi schema and the prose examples show `modelType` as required (absent `model_id`) and document the `400`; no example still posts an empty `params` without `modelType`.

---

## Verification Contract

- **Full suite:** `run/astrodash.test.sh slim_dev` -- runs `astrodash.tests` and `users.tests` with coverage inside the container. Must be green, including the new `test_api_model_type.py`.
- **Single module while iterating:** `docker compose <compose args> exec app_dev python manage.py test astrodash.tests.test_api_model_type -v 2` (compose args from `run/get_compose_args.sh slim_dev`).
- **New-contract proof:** the omitted / unknown / retired / `user_uploaded`-without-`model_id` scenarios return `400` with the KTD3 messages; a valid built-in and the `model_id` path behave as today.
- **Formatting:** `black` over the changed Python files (`views.py`, `test_api_model_type.py`).
- **Docs consistency:** the API docs examples and openapi schema match U1's contract (no `params='{}'`-without-`modelType` examples remain).

---

## Definition of Done

- R1-R8 satisfied: both endpoints resolve `modelType` through the shared registry-driven helper; no hardcoded allowed-set tuple or `"dash"` default literal remains in `process_spectrum` / `batch_process`.
- Omitted, unknown, and retired `modelType` (and `modelType="user_uploaded"` without `model_id`) return `400` with the three distinct messages; a valid active built-in classifies as today, and the `model_id` -> user-uploaded path is unchanged.
- Adding a model to the registry makes the endpoints accept it, and retiring one makes them reject it, with no edits to `views.py` -- demonstrated by the retire-in-a-test scenario (AE3).
- `estimate_redshift` is untouched (R6); no discovery endpoint added (R7).
- The published API contract (`openapi.json` + affected `docs/api/*`) documents `modelType` as required (without `model_id`) and the `400` responses (R8).
- The full suite plus coverage is green; changed Python is `black`-formatted.
