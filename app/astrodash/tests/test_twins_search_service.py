"""Tests for the Twins Search service's umap/pca-transform fallback path.

Under Python 3.13 + numba 0.65.1 + umap-learn 0.5.12, JIT-compiling
umap-learn's distance metric panics in numba's bytecode interpreter
(``byteflow.py:1641 op_BINARY_OP`` pops from an empty stack and raises
``IndexError('pop from empty list')``). Both sklearn's callable-metric
path and umap-learn's ``pairwise_special_metric`` fallback trigger the
same JIT compilation and panic identically — there's no try/except
shape that lets the in-library transform succeed.

The fix is to fall back to the nearest twin's payload coordinates so
the visualization lands in the right neighborhood instead of failing
the whole request.
"""

from unittest.mock import Mock

import numpy as np
from django.test import SimpleTestCase

from astrodash.domain.services.twins_search_service import TwinsSearchService


class ProjectWithFallbackTests(SimpleTestCase):
    """Unit tests for the ``_project_with_fallback`` helper in isolation."""

    def test_success_passes_through_transform_output(self):
        """When transform succeeds, the helper returns its 2D coords
        unchanged — no fallback path taken."""
        transform = Mock(return_value=np.array([[1.5, 2.5]]))
        out = TwinsSearchService._project_with_fallback(
            transform,
            np.zeros((1, 1024)),
            ([10.0, 20.0], [100.0, 200.0]),
            0,
            label="UMAP",
        )
        self.assertEqual(out, [1.5, 2.5])
        transform.assert_called_once()

    def test_index_error_pop_from_empty_list_falls_back(self):
        """The numba bytecode panic shape triggers the fallback path."""

        def transform(_):
            raise IndexError("pop from empty list")

        out = TwinsSearchService._project_with_fallback(
            transform,
            np.zeros((1, 1024)),
            ([10.0, 20.0, 30.0], [100.0, 200.0, 300.0]),
            1,
            label="UMAP",
        )
        self.assertEqual(out, [20.0, 200.0])

    def test_unrelated_exception_also_falls_back(self):
        """The fallback is intentionally broad — any exception from
        transform routes through the nearest-twin path so the endpoint
        keeps producing a renderable response."""

        def transform(_):
            raise ValueError("something unrelated")

        out = TwinsSearchService._project_with_fallback(
            transform,
            np.zeros((1, 1024)),
            ([10.0, 20.0], [100.0, 200.0]),
            0,
            label="PCA",
        )
        self.assertEqual(out, [10.0, 100.0])


class FindTwinsFallbackTests(SimpleTestCase):
    """Higher-level tests for the find_twins endpoint behavior with mocked
    UMAP and PCA components, exercising the fallback wiring end-to-end."""

    @staticmethod
    def _build_service(umap_mock, pca_mock):
        """Construct a TwinsSearchService without running __init__ (which
        requires real artifact files on disk). Populates the minimal
        attribute surface ``find_twins`` reads.

        The mocked normed-embedding matrix is rigged so that the query
        ``[1, 0, ..., 0]`` selects row 2 as the nearest twin.
        """
        svc = TwinsSearchService.__new__(TwinsSearchService)
        dim = 1024
        n = 5
        embeddings = np.zeros((n, dim), dtype=np.float32)
        embeddings[2, 0] = 1.0
        svc._embeddings = embeddings
        norms = np.linalg.norm(embeddings, axis=1, keepdims=True)
        norms = np.clip(norms, 1e-10, None)
        svc._normed = (embeddings / norms).astype(np.float32)
        svc._n = n
        svc._dim = dim
        svc._umap = umap_mock
        svc._pca = pca_mock
        svc._umap_xy = (
            [0.0, 0.1, 0.2, 0.3, 0.4],
            [1.0, 1.1, 1.2, 1.3, 1.4],
        )
        svc._pca_xy = (
            [10.0, 10.1, 10.2, 10.3, 10.4],
            [100.0, 100.1, 100.2, 100.3, 100.4],
        )
        return svc

    def _query_vector(self):
        q = np.zeros(1024, dtype=np.float32)
        q[0] = 1.0
        return q

    def test_umap_transform_failure_uses_nearest_twin_umap_coords(self):
        umap_mock = Mock()
        umap_mock.transform.side_effect = IndexError("pop from empty list")
        pca_mock = Mock()
        pca_mock.transform.return_value = np.array([[7.0, 8.0]])

        svc = self._build_service(umap_mock, pca_mock)
        out = svc.find_twins(self._query_vector(), k=3)

        # Row 2 is the nearest twin; UMAP falls back to payload index 2.
        self.assertEqual(out["twin_indices"][0], 2)
        self.assertEqual(out["query_umap"], [0.2, 1.2])
        # PCA succeeded — its output is preserved.
        self.assertEqual(out["query_pca"], [7.0, 8.0])

    def test_pca_transform_failure_uses_nearest_twin_pca_coords(self):
        umap_mock = Mock()
        umap_mock.transform.return_value = np.array([[5.5, 6.6]])
        pca_mock = Mock()
        pca_mock.transform.side_effect = RuntimeError("sklearn imploded")

        svc = self._build_service(umap_mock, pca_mock)
        out = svc.find_twins(self._query_vector(), k=3)

        self.assertEqual(out["twin_indices"][0], 2)
        self.assertEqual(out["query_umap"], [5.5, 6.6])
        self.assertEqual(out["query_pca"], [10.2, 100.2])

    def test_both_transforms_succeed_no_fallback_taken(self):
        umap_mock = Mock()
        umap_mock.transform.return_value = np.array([[5.5, 6.6]])
        pca_mock = Mock()
        pca_mock.transform.return_value = np.array([[7.0, 8.0]])

        svc = self._build_service(umap_mock, pca_mock)
        out = svc.find_twins(self._query_vector(), k=3)

        self.assertEqual(out["query_umap"], [5.5, 6.6])
        self.assertEqual(out["query_pca"], [7.0, 8.0])
        self.assertEqual(len(out["twin_indices"]), 3)
        self.assertEqual(len(out["twin_similarities"]), 3)
