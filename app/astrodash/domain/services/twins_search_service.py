"""
Domain service for DASH Twins similarity search.

Loads precomputed embeddings and fitted UMAP/PCA from the explorer artifacts
(dash_twins_embeddings.npy, dash_twins_umap.pkl, dash_twins_pca.pkl) and provides
cosine-similarity search and 2D projection for a query embedding (e.g. from a
user-uploaded spectrum).
"""

import json
import pickle
import warnings
from pathlib import Path

import numpy as np
from sklearn.exceptions import InconsistentVersionWarning

from astrodash.config.logging import get_logger

logger = get_logger(__name__)


class TwinsSearchService:
    """
    Service for finding nearest-neighbor "twins" in the DASH embedding space
    and projecting a query embedding into the same 2D (UMAP/PCA) as the payload.
    """

    def __init__(self, explorer_dir: Path):
        """
        Load artifacts from explorer_dir. Raises FileNotFoundError if any required file is missing.

        Args:
            explorer_dir: Directory containing dash_twins_embeddings.npy,
                dash_twins_umap.pkl, dash_twins_pca.pkl, and
                dash_twins_payload.json.
        """
        explorer_dir = Path(explorer_dir)
        emb_path = explorer_dir / "dash_twins_embeddings.npy"
        umap_path = explorer_dir / "dash_twins_umap.pkl"
        pca_path = explorer_dir / "dash_twins_pca.pkl"
        payload_path = explorer_dir / "dash_twins_payload.json"
        for p, name in [(emb_path, "embeddings"), (umap_path, "UMAP"), (pca_path, "PCA")]:
            if not p.is_file():
                raise FileNotFoundError(
                    f"Twins artifact not found: {p}. Run extract_payload.py --build-artifacts."
                )
        if not payload_path.is_file():
            raise FileNotFoundError(
                f"Twins artifact not found: {payload_path}. "
                f"Run extract_payload.py --build-artifacts."
            )

        self._embeddings = np.load(emb_path).astype(np.float32)
        with open(umap_path, "rb") as f:
            self._umap = pickle.load(f)
        # The pickled PCA was serialized by an older sklearn (currently 1.8.0
        # vs the runtime 1.9.0+), which surfaces an InconsistentVersionWarning
        # on every load. PCA pickles tend to survive minor sklearn bumps
        # cleanly — and this one does, find_twins returns sensible PCA coords
        # — so the warning is informational noise. Silence it only at this
        # specific load site so other (legitimately different) version
        # mismatches elsewhere still surface.
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", InconsistentVersionWarning)
            with open(pca_path, "rb") as f:
                self._pca = pickle.load(f)
        with open(payload_path, "r") as f:
            payload = json.load(f)
        # Only the 2D coordinate arrays are needed at query time — the rest of the
        # payload (spectra_db, names, types, phases, etc.) is served separately to
        # the frontend by dash_twins_data.
        self._umap_xy = (payload.get("umap_x", []), payload.get("umap_y", []))
        self._pca_xy = (payload.get("pca_x", []), payload.get("pca_y", []))

        n, dim = self._embeddings.shape
        if dim != 1024:
            raise ValueError(f"Expected embedding dimension 1024, got {dim}")
        self._n = n
        self._dim = dim

        # Precompute L2-normalized embeddings for cosine similarity (cos_sim = dot of normalized)
        norms = np.linalg.norm(self._embeddings, axis=1, keepdims=True)
        norms = np.clip(norms, 1e-10, None)
        self._normed = (self._embeddings / norms).astype(np.float32)
        logger.info("TwinsSearchService loaded: N=%d, dim=%d", n, dim)

    @property
    def n_spectra(self) -> int:
        """Number of spectra in the precomputed embedding matrix."""
        return self._n

    def find_twins(
        self,
        query_embedding: np.ndarray,
        k: int = 10,
    ) -> dict:
        """
        Find the k most similar spectra to the query embedding via cosine similarity,
        and project the query into the same 2D UMAP/PCA space as the payload.

        Args:
            query_embedding: 1D array of shape (1024,) or (1, 1024).
            k: Number of nearest neighbors to return.

        Returns:
            Dict with:
                - query_umap: [x, y] in UMAP space
                - query_pca: [x, y] in PCA space
                - twin_indices: list of k row indices (into the payload)
                - twin_similarities: list of k cosine similarities (1 = identical)
        """
        q = np.asarray(query_embedding, dtype=np.float32).ravel()
        if q.shape[0] != self._dim:
            raise ValueError(f"Query embedding must have length {self._dim}, got {q.shape[0]}")

        # Normalize query
        q_norm = np.linalg.norm(q)
        q_norm = np.clip(q_norm, 1e-10, None)
        q_unit = (q / q_norm).astype(np.float32)

        # Cosine similarities (already normalized DB)
        sims = self._normed @ q_unit
        top_k = np.argsort(sims)[::-1][:k]
        twin_indices = top_k.tolist()
        twin_similarities = sims[top_k].tolist()

        # Project query into 2D. Both UMAP and PCA transforms wrap in
        # try/except: on failure, fall back to the nearest twin's coordinates
        # from the payload so the dot in the explorer lands in the right
        # neighborhood instead of failing the whole request.
        #
        # The UMAP fallback exists because under Python 3.13 + numba 0.65.1
        # + umap-learn 0.5.12, JIT-compiling the distance metric panics in
        # numba's bytecode interpreter (byteflow.py:1641 op_BINARY_OP pops
        # from an empty stack and raises IndexError('pop from empty list')).
        # Both sklearn's callable-metric path and umap-learn's own
        # pairwise_special_metric fallback trigger the same JIT compilation
        # and panic identically. PCA goes through pure sklearn (no numba)
        # and shouldn't be affected, but the symmetric fallback keeps the
        # endpoint functional if anything analogous surfaces later.
        q_2d = q.reshape(1, -1)
        nearest_idx = int(twin_indices[0])
        query_umap = self._project_with_fallback(
            self._umap.transform,
            q_2d,
            self._umap_xy,
            nearest_idx,
            label="UMAP",
        )
        query_pca = self._project_with_fallback(
            self._pca.transform,
            q_2d,
            self._pca_xy,
            nearest_idx,
            label="PCA",
        )

        return {
            "query_umap": [float(query_umap[0]), float(query_umap[1])],
            "query_pca": [float(query_pca[0]), float(query_pca[1])],
            "twin_indices": twin_indices,
            "twin_similarities": twin_similarities,
        }

    @staticmethod
    def _project_with_fallback(transform, q_2d, payload_xy, nearest_idx, label):
        """Call ``transform(q_2d)`` and return the 2D coords as a list of two
        floats. On any exception, log it and fall back to the nearest twin's
        coordinates from ``payload_xy`` (a (xs, ys) tuple of arrays indexed
        the same as the payload). Raises ``IndexError`` only if the fallback
        path is needed but the payload arrays are empty — that means the
        artifact set is incomplete and the operator needs to rebuild it.
        """
        try:
            return transform(q_2d)[0].tolist()
        except Exception as exc:
            xs, ys = payload_xy
            logger.warning(
                "%s transform failed (%s: %s); falling back to nearest "
                "twin's %s coordinates (twin index %d).",
                label,
                type(exc).__name__,
                exc,
                label,
                nearest_idx,
            )
            return [float(xs[nearest_idx]), float(ys[nearest_idx])]
