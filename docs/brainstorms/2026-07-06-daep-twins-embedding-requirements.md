---
date: 2026-07-06
topic: daep-twins-embedding
---

# DAEP-Powered Spectral Twins

## Summary

Replace the embedding model behind the **FIND TWINS** feature. Today the Twins
Explorer borrows the DASH CNN's penultimate-layer activation (a 1024-D vector)
as its embedding; the reference set and the uploaded query are both embedded
that way, then matched by cosine similarity. This work swaps that embedding for
**DAEP** (Diffusion Autoencoder with Perceivers), a purpose-built spectral
representation model developed by Henna Abunemeh (UIUC). The app integrates
Henna's DAEP encoder and preprocessing to embed the uploaded query spectrum at
request time, and matches it against her precomputed DAEP reference embeddings
using the existing `TwinsSearchService` cosine search. The Twins Explorer UI and
its UMAP/PCA visualization are reused, repointed at DAEP-derived artifacts. The
feature stays gated behind a DASH classification, exactly as today.

## Problem Frame

AstroDash has two orthogonal ML axes, and the DAEP work touches only the second:

- **Axis 1 - classifiers (output a class label).** `dash_classifier.py` (DASH
  CNN), `transformer_classifier.py` (Transformer), and `user_classifier.py`
  (user-uploaded), selected by the `modelType` dropdown. This is the STRATEGY.md
  "Model library & curation" track. The PI's intent to replace the Transformer
  classifier with **BERTIE** lives here and is **out of scope** for this doc.

- **Axis 2 - the twins embedding (outputs a latent vector, no label).** FIND
  TWINS does not classify; it embeds a spectrum into a vector space and returns
  nearest neighbors by cosine distance. It currently has **no model of its
  own** - it piggybacks on DASH's penultimate layer, and the query embedding is
  only stashed "when DASH and embedding present" (`ui_views.py:638`). So twins
  only works after a DASH classification.

DAEP is an Axis-2 model. It is not a third classifier and does not compete with
BERTIE. Its role is to give the twins feature a **dedicated, purpose-built
embedding** instead of borrowing DASH's internals.

Why swap at all: DAEP is trained specifically to measure full-spectrum
spectroscopic similarity (diffusion-autoencoder reconstruction objective over a
homogenized rest-frame grid), rather than being a side effect of a
classification network. Henna's second-year document ("Learning Spectroscopic
Similarity in Supernovae with Diffusion Autoencoders", draft 2026-07-06,
`Abunemeh_2ndyeardoc.pdf`) reports high reconstruction fidelity and a latent
space that recovers subtype structure and observed-to-simulated correspondence.

The mechanics that make this a bounded swap already exist: `TwinsSearchService`
already loads a reference embedding matrix + UMAP + PCA + payload from
`{data_dir}/explorer/` and does cosine search with UMAP/PCA projection; the
Explorer UI already renders that payload; and the classifiers already
demonstrate the pattern for serving a Torch model from the data mount
(`model_factory`, `transformer_model_path`). What is missing is a DAEP encoder in
the app's query path and DAEP-derived reference artifacts in place of the
DASH-derived ones.

## What DAEP is (reference)

- **Model.** Diffusion Autoencoder with Perceivers (Abunemeh, adapting Shen &
  Gagliano 2025). A Perceiver-style encoder compresses a spectrum into a compact
  latent bottleneck; a diffusion decoder reconstructs the spectrum from that
  latent. **Only the encoder is needed for twins** - the diffusion decoder is a
  reconstruction/validation component and is not required at query time.
- **Latent.** 16 latent tokens x 64 dims = **1024 features**, flattened to a
  1024-vector for similarity. (Coincidentally the same length as the current
  DASH embedding, but a different space - they are not interchangeable.)
- **Metric.** Cosine similarity / cosine distance `D = 1 - s`, ranked ascending.
  This matches what `TwinsSearchService` already computes.
- **Input / preprocessing.** Spectrum on a common rest-frame grid 3200-9800 A at
  5 A spacing (**1320 bins**), with flux + wavelength + a boolean validity mask.
  Steps: rest-frame transform using redshift `z`; Milky Way extinction
  correction (CCM89 law, SFD dust maps looked up by sky coordinates); flux-
  conserving resampling onto the grid (via `specutils`); telluric masking at
  6850-6900 A and 7590-7650 A; P90 flux normalization
  `f / P90(|f|)`. Host-galaxy extinction is not corrected. Phase is not an input.
- **Trained variants.** Two models: WISeREP-only (36,554 observed spectra) and
  WISeREP+SASSAFRAS combined (91,651, adds simulated spectra for broader
  coverage).

## Key Decisions

- **DAEP replaces the twins embedding source; twins stays DASH-gated.** The
  uploaded spectrum is embedded in DAEP's space (not DASH's), and matched against
  DAEP reference embeddings. The gate ("FIND TWINS available only after a DASH
  classification") is preserved as a UX condition. Decoupling twins from the
  classifier - so it works for any upload regardless of classifier - is a
  possible later step DAEP enables, but is deferred.

- **The gate is a UX condition, not an embedding shortcut.** Even gated, the app
  must embed the query in DAEP space at request time: cosine similarity is only
  meaningful within one embedding space, so a DASH query vector cannot be matched
  against DAEP references. "DASH-gated" saves wiring twins into the
  Transformer/BERTIE/user-upload flows; it does not remove the app-side DAEP
  encoder or the preprocessing.

- **Integrate Henna's encoder + preprocessing, do not rebuild them.** Henna
  delivers the DAEP reference embeddings, the trained encoder weights, and her
  preprocessing code (importable). The app wraps and serves them. Preprocessing
  parity with the reference set is thereby inherited from her code rather than
  reimplemented and kept in sync by hand.

- **Serve the DAEP encoder inline as a Torch model.** Mirror the existing
  DASH/Transformer pattern: encoder weights live on the `/mnt/astrodash-data`
  mount alongside the other models, loaded once and invoked at twins-search time.
  Torch is already a dependency.

- **Reuse `TwinsSearchService`, the cosine metric, and the Explorer UI.** Only
  the artifacts they point at change (DAEP-derived embeddings + UMAP + PCA +
  payload replace the DASH-derived ones in `{data_dir}/explorer/`). The service's
  hard `dim == 1024` check happens to still pass, but the space is different, so
  all four artifacts must be rebuilt from DAEP together - a DAEP query embedding
  must never be matched against a DASH reference set, or vice versa.

- **Reference set: WISeREP-only (recommended, confirm).** So every twin a user
  is shown is a real observed supernova, not a simulated SASSAFRAS spectrum. The
  combined model has broader coverage but would surface simulated objects as
  "twins," which is confusing without clear source labeling. Confirm with the
  team; see Outstanding Questions.

## Requirements

### Query-time embedding (app-side)

- R1. When FIND TWINS runs, the app embeds the uploaded spectrum with the DAEP
  encoder in DAEP's latent space (1024-D), using Henna's preprocessing to place
  the spectrum on the 1320-bin 3200-9800 A rest-frame grid with validity mask and
  P90 normalization.
- R2. The DAEP encoder is loaded once from the data mount and invoked per query
  (encoder forward pass only; no diffusion decoder). Loading follows the existing
  Torch-model-from-mount pattern used for DASH and Transformer.
- R3. The query embedding is matched against the DAEP reference set by the
  existing `TwinsSearchService` cosine search, returning the same result shape
  (`twin_indices`, `twin_similarities`, `query_umap`, `query_pca`) so the
  Explorer UI is unchanged.

### Reference artifacts

- R4. The DAEP reference artifacts (embedding matrix, UMAP, PCA, payload)
  replace the current DASH-derived artifacts in `{data_dir}/explorer/`. Query
  embeddings and reference embeddings are always from the same DAEP model.
- R5. The reference set is built from a single, recorded DAEP model variant
  (WISeREP-only per the current recommendation). The variant used is documented
  so query encoding uses the matching encoder weights.

### Gating and unchanged surfaces

- R6. FIND TWINS remains gated behind a DASH classification (current UX). No
  twins entry point is added to the Transformer, BERTIE, or user-uploaded flows
  in this work.
- R7. DASH and Transformer classification behavior is unchanged. DASH continues
  to produce its own penultimate-layer embedding for classification; that
  embedding is simply no longer the twins query vector.
- R8. The Twins Explorer UI, its UMAP/PCA toggle, spectrum overlay, and top-k
  list are reused as-is, driven by the DAEP-derived payload.

### Verification

- R9. Parity check: re-embedding a known reference spectrum through the app's
  query path reproduces Henna's stored reference embedding for that spectrum
  within a documented tolerance (cosine similarity at or above an agreed
  threshold). This is the primary acceptance signal that the app-side encoder and
  preprocessing match the reference build.

## Success Criteria

- A user classifies a spectrum with DASH, clicks FIND TWINS, and sees nearest
  neighbors computed in DAEP's latent space, with the query correctly projected
  into the DAEP UMAP/PCA scatter.
- The parity check (R9) passes for a sample of reference spectra.
- No regression in DASH/Transformer classification or in the Explorer UI.

## Explicitly Out of Scope

- BERTIE and the Transformer-classifier replacement (Axis 1, separate track).
- Decoupling twins from the classifier so it works for any upload (deferred;
  DAEP makes it possible later).
- Any new twins UI beyond repointing to DAEP artifacts.
- Serving or using the DAEP diffusion decoder / reconstruction.
- Multi-epoch "trajectory" twin analysis and observed-to-simulated diagnostics
  from Henna's paper (research directions, not app features here).

## Outstanding Questions

1. **Deliverable interface (top dependency).** Confirm with Henna the concrete
   form of the handoff: encoder weights format (state_dict / TorchScript /
   checkpoint) and the exact architecture needed to load them; the preprocessing
   entrypoint (importable function, signature, inputs it expects - flux,
   wavelength, z, coordinates?); and that encoding is deterministic (eval mode, no
   dropout, fixed given the same input).
2. **Model variant.** WISeREP-only vs WISeREP+SASSAFRAS as the reference set +
   matching query encoder. Recommendation: WISeREP-only (real events only).
3. **MW-extinction coordinates for user uploads.** Her reference preprocessing
   corrected Milky Way extinction using SFD dust maps looked up by RA/Dec.
   AstroDash has redshift for uploads but may not have sky coordinates. If
   coordinates are unavailable at query time, decide how her preprocessing
   behaves (skip extinction? require coordinates?) and whether that breaks parity
   with a reference set that was extinction-corrected. This is the sharpest
   parity risk.
4. **New dependencies and cost.** `specutils` and SFD dust-map data are likely
   new to the app image; confirm footprint. Measure per-query encoder
   forward-pass latency on CPU (the deploy target) to confirm it fits the
   twins-search request budget.
5. **Naming.** The feature, artifacts, and templates are branded "DASH Twins"
   (`dash_twins.html`, `dash_twins_payload.json`, "DASH Twins Explorer"). With a
   DAEP embedding, decide whether to keep the brand or rename (e.g. "Spectral
   Twins"). Low stakes; a rename touches artifact filenames and `TwinsSearchService`
   paths.
6. **Artifact provenance / rebuild path.** The current artifacts are built by
   `extract_payload.py --build-artifacts` from DASH. Decide whether DAEP
   artifacts are dropped in from Henna directly or regenerated through an updated
   build script, and where the source of truth lives for future rebuilds.

## Adjacent Context (not this work)

- **BERTIE** replaces the **Transformer classifier** (Axis 1) per the PI's Slack
  ("instead of DASH and Transformer -> DASH and BERTIE"). Assumption: BERTIE is a
  BERT-style transformer classifier; confirm with the PI. Orthogonal to DAEP.
- If twins is later **decoupled** from the classifier, DAEP-powered twins would
  become available for any upload (including BERTIE classifications), since the
  query embedding no longer depends on DASH. Noted as a future direction.
