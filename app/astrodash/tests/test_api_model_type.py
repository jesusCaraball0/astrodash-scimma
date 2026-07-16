"""REST contract tests: the classify/batch endpoints resolve ``modelType``
through the model registry.

These lock the new contract shipped by U1 of the REST model-registry plan: the
``process_spectrum`` and ``batch_process`` endpoints no longer carry a
hardcoded allowed-set or ``"dash"`` default. Instead they validate the
client-supplied ``modelType`` against the registry's active definitions --
omitted, unknown, or retired values return ``400`` (replacing today's silent
coercion to ``"dash"``), while the ``model_id`` -> user-uploaded path and valid
active built-ins are unchanged.

Both endpoints are gated by ``api_writes_required``; the tests patch
``views.API_WRITES_ENABLED`` on so the view body runs. The classification and
batch services are mocked, so no model weights or network access are needed
(the same technique the PR #1 view-gate tests use). No async DB/filesystem work
runs unmocked, so there is no persistent-executor connection leak.
"""

from dataclasses import replace
from unittest.mock import AsyncMock, MagicMock, patch

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, SimpleTestCase
from django.urls import reverse

from astrodash.infrastructure.ml import model_registry


def _mock_classification(model_type):
    """Build a fake classification result the classify payload can serialize."""
    fake_processed = MagicMock()
    fake_processed.x = [3000.0, 5000.0, 9000.0]
    fake_processed.y = [1.0, 2.0, 1.0]
    fake_processed.redshift = 0.0

    fake_classification = MagicMock()
    fake_classification.model_type = model_type
    fake_classification.results = {"best_matches": []}

    spectrum_svc = MagicMock(
        get_spectrum_data=AsyncMock(return_value=MagicMock()),
        save_spectrum=AsyncMock(return_value=None),
    )
    processing_svc = MagicMock(
        process_spectrum_with_params=AsyncMock(return_value=fake_processed)
    )
    classification_svc = MagicMock(
        classify_spectrum=AsyncMock(return_value=fake_classification)
    )
    return spectrum_svc, processing_svc, classification_svc


class ClassifyModelTypeContractTests(SimpleTestCase):
    """The classify endpoint validates ``modelType`` against the registry."""

    def setUp(self):
        self.client = Client()
        self.url = reverse("astrodash_api:process_spectrum")

    def _post(self, data):
        """POST to the classify endpoint with API writes enabled."""
        with patch("astrodash.views.API_WRITES_ENABLED", True):
            return self.client.post(self.url, data=data)

    def _post_with_services(self, data):
        """POST with the spectrum/classification services mocked."""
        model_type = data.get("_expected_model_type")
        spectrum_svc, processing_svc, classification_svc = _mock_classification(
            model_type
        )
        post_data = {k: v for k, v in data.items() if not k.startswith("_")}
        with patch("astrodash.views.API_WRITES_ENABLED", True), patch(
            "astrodash.views.get_spectrum_service", return_value=spectrum_svc
        ), patch(
            "astrodash.views.get_spectrum_processing_service",
            return_value=processing_svc,
        ), patch(
            "astrodash.views.get_classification_service",
            return_value=classification_svc,
        ):
            resp = self.client.post(self.url, data=post_data)
        return resp, classification_svc

    # --- 400 paths (the new contract; these fail on today's silent-coerce) ---

    def test_omitted_model_type_returns_400(self):
        """AE1: no model_id and no modelType -> 400 'modelType is required.'"""
        spectrum_svc, processing_svc, classification_svc = _mock_classification("dash")
        with patch("astrodash.views.API_WRITES_ENABLED", True), patch(
            "astrodash.views.get_classification_service",
            return_value=classification_svc,
        ):
            resp = self.client.post(self.url, data={"params": "{}"})
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.json()["detail"], "modelType is required.")
        classification_svc.classify_spectrum.assert_not_called()

    def test_unknown_model_type_returns_400(self):
        """AE2: modelType='bogus' -> 400, not silently classified as DASH."""
        spectrum_svc, processing_svc, classification_svc = _mock_classification("dash")
        with patch("astrodash.views.API_WRITES_ENABLED", True), patch(
            "astrodash.views.get_classification_service",
            return_value=classification_svc,
        ):
            resp = self.client.post(self.url, data={"params": '{"modelType": "bogus"}'})
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.json()["detail"], "Unknown model type: bogus.")
        classification_svc.classify_spectrum.assert_not_called()

    def test_retired_model_type_returns_400(self):
        """AE3: a retired registry model -> 400, with no edit to views.py."""
        transformer = model_registry.get_definition("transformer")
        dash = model_registry.get_definition("dash")
        patched = (
            replace(transformer, status=model_registry.STATUS_RETIRED),
            replace(dash, is_default=True),
        )
        with patch.object(model_registry, "MODELS", patched):
            resp = self._post(data={"params": '{"modelType": "transformer"}'})
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(
            resp.json()["detail"], "Model type transformer is not available."
        )

    def test_user_uploaded_literal_without_model_id_returns_400(self):
        """R5 corner case: modelType='user_uploaded' with no model_id -> 400.

        It is not a client-selectable built-in (it is derived from model_id
        presence), so the registry lookup misses and it is rejected.
        """
        resp = self._post(data={"params": '{"modelType": "user_uploaded"}'})
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.json()["detail"], "Unknown model type: user_uploaded.")

    # --- unchanged paths (parity) ---

    def test_valid_transformer_classifies_as_today(self):
        """AE4: active modelType='transformer' reaches the classification service."""
        resp, classification_svc = self._post_with_services(
            {
                "params": '{"modelType": "transformer"}',
                "_expected_model_type": "transformer",
            }
        )
        self.assertEqual(resp.status_code, 200)
        classification_svc.classify_spectrum.assert_called_once()
        self.assertEqual(
            classification_svc.classify_spectrum.call_args.kwargs["model_type"],
            "transformer",
        )
        # The resolved model_type is echoed back in the response payload.
        self.assertEqual(resp.json()["model_type"], "transformer")

    def test_model_id_wins_over_modeltype_and_routes_to_user_uploaded(self):
        """AE5: a model_id resolves to user_uploaded and takes precedence.

        A valid, competing ``modelType`` is supplied alongside the ``model_id``
        to prove ``model_id`` wins -- a regression that consulted ``modelType``
        first would classify as transformer and fail here.
        """
        resp, classification_svc = self._post_with_services(
            {
                "params": '{"modelType": "transformer"}',
                "model_id": "abc-123",
                "_expected_model_type": "user_uploaded",
            }
        )
        self.assertEqual(resp.status_code, 200)
        classification_svc.classify_spectrum.assert_called_once()
        kwargs = classification_svc.classify_spectrum.call_args.kwargs
        self.assertEqual(kwargs["model_type"], "user_uploaded")
        self.assertEqual(kwargs["user_model_id"], "abc-123")
        self.assertEqual(resp.json()["model_type"], "user_uploaded")


class BatchModelTypeContractTests(SimpleTestCase):
    """The batch endpoint applies the same registry-driven ``modelType`` rule."""

    def setUp(self):
        self.client = Client()
        self.url = reverse("astrodash_api:batch_process")

    def _post(self, params, model_id=None):
        """POST a one-file batch request with the batch service mocked.

        The service is always mocked so the 400 tests can assert the endpoint
        short-circuits before invoking it (the resolver rejects an invalid
        modelType before ``get_batch_processing_service`` is reached).

        Returns:
            A ``(response, batch_svc)`` tuple; ``batch_svc.process_batch`` is an
            ``AsyncMock`` returning a serializable result.
        """
        upload = SimpleUploadedFile("spectrum.dat", b"3000 1.0\n5000 2.0\n")
        data = {"params": params, "files": upload}
        if model_id is not None:
            data["model_id"] = model_id
        batch_svc = MagicMock(process_batch=AsyncMock(return_value={"results": []}))
        with patch("astrodash.views.API_WRITES_ENABLED", True), patch(
            "astrodash.views.get_batch_processing_service", return_value=batch_svc
        ):
            resp = self.client.post(self.url, data=data)
        return resp, batch_svc

    def test_omitted_model_type_returns_400(self):
        resp, batch_svc = self._post(params="{}")
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.json()["detail"], "modelType is required.")
        batch_svc.process_batch.assert_not_called()

    def test_unknown_model_type_returns_400(self):
        resp, batch_svc = self._post(params='{"modelType": "bogus"}')
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.json()["detail"], "Unknown model type: bogus.")
        batch_svc.process_batch.assert_not_called()

    def test_retired_model_type_returns_400(self):
        transformer = model_registry.get_definition("transformer")
        dash = model_registry.get_definition("dash")
        patched = (
            replace(transformer, status=model_registry.STATUS_RETIRED),
            replace(dash, is_default=True),
        )
        with patch.object(model_registry, "MODELS", patched):
            resp, batch_svc = self._post(params='{"modelType": "transformer"}')
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(
            resp.json()["detail"], "Model type transformer is not available."
        )
        batch_svc.process_batch.assert_not_called()

    def test_valid_dash_reaches_batch_service(self):
        resp, batch_svc = self._post(params='{"modelType": "dash"}')
        self.assertEqual(resp.status_code, 200)
        batch_svc.process_batch.assert_called_once()
        # process_batch(payload, params, model_type, model_id) -- positional.
        self.assertEqual(batch_svc.process_batch.call_args.args[2], "dash")

    def test_model_id_routes_to_user_uploaded_unchanged(self):
        """The model_id -> user_uploaded path is preserved on the batch endpoint.

        Mirrors the classify AE5 parity: a present model_id makes modelType
        optional and routes to the user-uploaded model unchanged.
        """
        resp, batch_svc = self._post(params="{}", model_id="abc-123")
        self.assertEqual(resp.status_code, 200)
        batch_svc.process_batch.assert_called_once()
        # process_batch(payload, params, model_type, model_id) -- positional.
        self.assertEqual(batch_svc.process_batch.call_args.args[2], "user_uploaded")
        self.assertEqual(batch_svc.process_batch.call_args.args[3], "abc-123")
