"""Characterization tests locking current classifier behavior (plan U1).

These pin the observable behavior of the two built-in models (DASH,
Transformer) at the form / service / view-gate seam -- deliberately without a
live model forward pass -- so the model-registry refactor (U2-U5) can prove it
preserved behavior. They must pass on the pre-refactor code and stay green
through every later unit.

The classification-dependent gates (twins stash, template overlays) are
exercised by driving the classify view with the spectrum/processing/
classification services mocked, so no weights or network access are needed.
"""

import re
from unittest.mock import AsyncMock, MagicMock, patch

from asgiref.sync import async_to_sync
from django.http import HttpResponse
from django.test import Client, TestCase
from django.urls import reverse

from astrodash.forms import ClassifyForm
from astrodash.ui_views import _format_batch_results
from astrodash.domain.services.redshift_service import RedshiftService


class SelectModelPageParityTests(TestCase):
    """AE1: the select-model page offers exactly the two built-in cards."""

    def _render_visible(self):
        """Render the select-model page and return its body with comments stripped.

        Returns:
            str: The rendered HTML with ``<!-- ... -->`` comments removed. The
            user-model/upload cards live inside comments ("functionality
            preserved, visuals disabled"), so they appear in the raw body but
            are not selectable; parity is about the *visible* cards.
        """
        # Mock the model service so the page's async list_models() call does no
        # real DB/filesystem work: it keeps the test hermetic (independent of
        # any uploaded user models) and avoids leaving a connection open in
        # asgiref's executor thread, which would break the suite's DROP DATABASE
        # teardown.
        model_svc = MagicMock(list_models=AsyncMock(return_value=[]))
        with patch("astrodash.ui_views.get_model_service", return_value=model_svc):
            resp = self.client.get(
                reverse("astrodash:model_selection") + "?action=classify"
            )
        self.assertEqual(resp.status_code, 200)
        return re.sub(r"<!--.*?-->", "", resp.content.decode(), flags=re.DOTALL)

    def test_only_dash_and_transformer_cards_are_selectable(self):
        visible = self._render_visible()
        # A *selectable card* is an element with an onclick="selectModel('...')"
        # attribute. (The bare selectModel('upload') call in the page's own
        # JavaScript is not a card, so match the attribute form specifically.)
        self.assertIn("onclick=\"selectModel('transformer')\"", visible)
        self.assertIn("onclick=\"selectModel('dash')\"", visible)
        self.assertNotIn("onclick=\"selectModel('user_model')\"", visible)
        self.assertNotIn("onclick=\"selectModel('upload')\"", visible)

    def test_cards_render_titles_descriptions_tags_badge_icon_and_order(self):
        visible = self._render_visible()
        # Titles and descriptions, unchanged from the hand-written cards.
        self.assertIn("Transformer Model", visible)
        self.assertIn("Dash Model", visible)
        self.assertIn(
            "Advanced transformer-based model with 5-class classification", visible
        )
        self.assertIn("CNN-based model from the original DASH paper", visible)
        # Feature tags for both models.
        for tag in ("Transformer", "5 Classes", "Fast Inference"):
            self.assertIn(f">{tag}</span>", visible)
        for tag in ("CNN", "Template Matching", "RLap Scores"):
            self.assertIn(f">{tag}</span>", visible)
        # DASH's RECOMMENDED badge and flask icon, and only DASH's.
        self.assertEqual(visible.count("RECOMMENDED"), 1)
        self.assertIn("bi-flask", visible)
        # Order: Transformer card precedes DASH card, as today.
        self.assertLess(
            visible.index("onclick=\"selectModel('transformer')\""),
            visible.index("onclick=\"selectModel('dash')\""),
        )

    def test_no_per_model_data_model_type_css_rule_remains(self):
        visible = self._render_visible()
        # The selected-state color is applied inline from data-color; no static
        # CSS rule keyed by data-model-type should remain.
        self.assertNotIn(".model-card.selected[data-model-type", visible)


class ClassifyFormRedshiftParityTests(TestCase):
    """AE2 / AE3: Transformer requires a redshift; DASH does not."""

    def _base_data(self, model):
        return {
            "supernova_name": "SN2011fe",
            "model": model,
            "smoothing": 0,
            "min_wave": 3500,
            "max_wave": 10000,
        }

    def test_transformer_requires_redshift(self):
        form = ClassifyForm(data=self._base_data("transformer"))
        self.assertFalse(form.is_valid())
        self.assertIn("redshift", form.errors)
        self.assertTrue(
            any(
                "Redshift is required for Transformer" in e
                for e in form.errors["redshift"]
            )
        )

    def test_dash_does_not_require_redshift(self):
        form = ClassifyForm(data=self._base_data("dash"))
        self.assertTrue(form.is_valid(), form.errors)


class BatchRlapParityTests(TestCase):
    """RLAP is populated only for DASH and only when requested."""

    def _results(self):
        return {
            "a.dat": {
                "classification": {
                    "best_match": {
                        "type": "Ia",
                        "age": "2 to 6",
                        "probability": 0.9,
                        "redshift": 0.01,
                        "rlap": 7.5,
                    }
                }
            }
        }

    def test_rlap_populated_for_dash_when_requested(self):
        out = _format_batch_results(
            self._results(), {"modelType": "dash", "calculateRlap": True}
        )
        self.assertEqual(out["a.dat"]["rlap"], 7.5)

    def test_rlap_absent_for_transformer(self):
        out = _format_batch_results(
            self._results(), {"modelType": "transformer", "calculateRlap": True}
        )
        self.assertEqual(out["a.dat"]["rlap"], "-")

    def test_rlap_absent_when_not_requested(self):
        out = _format_batch_results(
            self._results(), {"modelType": "dash", "calculateRlap": False}
        )
        self.assertEqual(out["a.dat"]["rlap"], "-")


class RedshiftEstimationGateParityTests(TestCase):
    """Redshift estimation is refused for any non-DASH model."""

    def test_non_dash_is_rejected(self):
        svc = RedshiftService()
        out = async_to_sync(svc.estimate_redshift_from_spectrum)(
            [4000.0, 5000.0, 6000.0],
            [1.0, 1.0, 1.0],
            "Ia",
            "2 to 6",
            model_type="transformer",
        )
        self.assertIsNone(out["estimated_redshift"])
        self.assertIn("only available for DASH", out["message"])


class ClassifyViewGateParityTests(TestCase):
    """AE4: twins stash + template-overlay eligibility, gated on the model.

    The three service getters are mocked so the view runs its gate logic on a
    constructed classification result without any model weights. `render` is
    patched out so template rendering can't interfere; the gate outcomes are
    read back from the session, which the view writes before any plotting.
    """

    def _run_classify(self, model_type):
        client = Client()
        session = client.session
        session["selected_model_type"] = model_type
        session.save()

        fake_processed = MagicMock()
        fake_processed.x = [3000.0, 5000.0, 9000.0]
        fake_processed.y = [1.0, 2.0, 1.0]

        fake_classification = MagicMock()
        fake_classification.model_type = model_type
        fake_classification.results = {"best_matches": [], "embedding": [0.0] * 1024}

        spectrum_svc = MagicMock(get_spectrum_data=AsyncMock(return_value=MagicMock()))
        processing_svc = MagicMock(
            process_spectrum_with_params=AsyncMock(return_value=fake_processed)
        )
        classification_svc = MagicMock(
            classify_spectrum=AsyncMock(return_value=fake_classification)
        )

        data = {
            "supernova_name": "SN2011fe",
            "model": model_type,
            "smoothing": 0,
            "min_wave": 3500,
            "max_wave": 10000,
        }
        if model_type == "transformer":
            data["redshift"] = "0.005"

        with patch(
            "astrodash.ui_views.get_spectrum_service", return_value=spectrum_svc
        ), patch(
            "astrodash.ui_views.get_spectrum_processing_service",
            return_value=processing_svc,
        ), patch(
            "astrodash.ui_views.get_classification_service",
            return_value=classification_svc,
        ), patch(
            "astrodash.ui_views.render", return_value=HttpResponse(b"")
        ):
            client.post(reverse("astrodash:classify"), data=data)
        return client.session

    def test_dash_stashes_twins_embedding_and_enables_templates(self):
        session = self._run_classify("dash")
        self.assertEqual(session.get("classify_dash_embedding"), [0.0] * 1024)
        self.assertTrue(session.get("classify_show_templates_section"))

    def test_transformer_no_twins_embedding_and_no_templates(self):
        session = self._run_classify("transformer")
        self.assertNotIn("classify_dash_embedding", session)
        self.assertFalse(session.get("classify_show_templates_section"))
