"""Unit tests for the central model registry (plan U2).

These pin the registry's own contract -- ordering, default resolution,
capability fields, retirement, and the exactly-one-default invariant -- before
any read site consumes it. They are pure in-memory tests: no database, no model
weights.
"""

from dataclasses import replace
from unittest.mock import patch

from django.test import SimpleTestCase

from astrodash.infrastructure.ml import model_registry as registry
from astrodash.infrastructure.ml.classifiers.dash_classifier import DashClassifier
from astrodash.infrastructure.ml.classifiers.transformer_classifier import (
    TransformerClassifier,
)


class RegistryOrderingTests(SimpleTestCase):
    def test_active_definitions_are_transformer_then_dash(self):
        ids = [d.id for d in registry.active_definitions()]
        self.assertEqual(ids, ["transformer", "dash"])

    def test_default_is_transformer(self):
        self.assertEqual(registry.default_definition().id, "transformer")


class DefinitionFieldsTests(SimpleTestCase):
    def test_dash_capability_fields(self):
        dash = registry.get_definition("dash")
        self.assertIsNotNone(dash)
        self.assertFalse(dash.requires_redshift)
        self.assertTrue(dash.supports_twins)
        self.assertTrue(dash.supports_redshift_estimation)
        self.assertTrue(dash.supports_template_overlays)
        self.assertTrue(dash.supports_rlap)
        self.assertEqual(dash.preprocessing, "dash")
        self.assertTrue(dash.recommended)
        self.assertIs(dash.classifier, DashClassifier)

    def test_transformer_capability_fields(self):
        tr = registry.get_definition("transformer")
        self.assertIsNotNone(tr)
        self.assertTrue(tr.requires_redshift)
        self.assertFalse(tr.supports_twins)
        self.assertFalse(tr.supports_redshift_estimation)
        self.assertFalse(tr.supports_template_overlays)
        self.assertFalse(tr.supports_rlap)
        self.assertEqual(tr.preprocessing, "transformer")
        self.assertTrue(tr.is_default)
        self.assertIs(tr.classifier, TransformerClassifier)

    def test_unknown_id_resolves_to_none(self):
        self.assertIsNone(registry.get_definition("user_uploaded"))
        self.assertIsNone(registry.get_definition("nope"))


class RetirementTests(SimpleTestCase):
    """AE5: retiring a model hides it from active surfaces but still resolves it."""

    def test_retired_model_drops_from_active_but_still_resolves(self):
        transformer = registry.get_definition("transformer")
        dash = registry.get_definition("dash")
        # Retire Transformer and promote DASH to default so the invariant holds.
        retired_transformer = replace(transformer, status=registry.STATUS_RETIRED)
        promoted_dash = replace(dash, is_default=True)
        patched = (retired_transformer, promoted_dash)

        with patch.object(registry, "MODELS", patched):
            active_ids = [d.id for d in registry.active_definitions()]
            self.assertEqual(active_ids, ["dash"])
            self.assertEqual(registry.default_definition().id, "dash")
            # Still resolvable for label/field lookups by any stored result.
            still = registry.get_definition("transformer")
            self.assertIsNotNone(still)
            self.assertEqual(still.title, "Transformer Model")
            self.assertFalse(still.is_active)


class InvariantTests(SimpleTestCase):
    def test_two_active_defaults_raises(self):
        transformer = registry.get_definition("transformer")
        dash = registry.get_definition("dash")
        both_default = (transformer, replace(dash, is_default=True))
        with self.assertRaises(ValueError):
            registry.validate_registry(both_default)

    def test_zero_active_defaults_raises(self):
        transformer = registry.get_definition("transformer")
        dash = registry.get_definition("dash")
        none_default = (replace(transformer, is_default=False), dash)
        with self.assertRaises(ValueError):
            registry.validate_registry(none_default)

    def test_duplicate_ids_raise(self):
        transformer = registry.get_definition("transformer")
        with self.assertRaises(ValueError):
            registry.validate_registry((transformer, transformer))

    def test_production_registry_is_valid(self):
        # Should not raise.
        registry.validate_registry(registry.MODELS)
