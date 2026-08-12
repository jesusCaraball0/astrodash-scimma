"""Unit tests for the central model registry (plan U2).

These pin the registry's own contract -- ordering, default resolution,
capability fields, retirement, and the exactly-one-default invariant -- before
any read site consumes it. They are pure in-memory tests: no database, no model
weights.
"""

import os
from dataclasses import replace
from unittest.mock import patch

from django.test import SimpleTestCase, override_settings

from astrodash.core import gate_config
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

    def test_gated_and_listed_raises(self):
        """R26: a model requiring a credential may never be listed."""
        transformer = registry.get_definition("transformer")
        dash = registry.get_definition("dash")
        gated_but_listed = replace(dash, requires_credential=True, listed=True)
        with self.assertRaises(ValueError) as ctx:
            registry.validate_registry((transformer, gated_but_listed))
        self.assertIn("dash", str(ctx.exception))

    def test_gated_default_raises(self):
        """R26: the active default may never require a credential."""
        transformer = registry.get_definition("transformer")
        gated_default = replace(transformer, requires_credential=True, listed=False)
        with self.assertRaises(ValueError) as ctx:
            registry.validate_registry((gated_default,))
        self.assertIn("transformer", str(ctx.exception))

    def test_unlisted_default_raises(self):
        """R26: the active default is always listed."""
        transformer = registry.get_definition("transformer")
        dash = registry.get_definition("dash")
        unlisted_default = replace(transformer, listed=False)
        with self.assertRaises(ValueError) as ctx:
            registry.validate_registry((unlisted_default, dash))
        self.assertIn("transformer", str(ctx.exception))


class ListingTests(SimpleTestCase):
    """R1/KD1: listing is independent of lifecycle status."""

    def test_unlisted_active_model_drops_from_listed_only(self):
        transformer = registry.get_definition("transformer")
        dash = registry.get_definition("dash")
        unlisted_dash = replace(dash, listed=False)
        patched = (transformer, unlisted_dash)

        with patch.object(registry, "MODELS", patched):
            self.assertEqual(
                [d.id for d in registry.active_definitions()],
                ["transformer", "dash"],
            )
            self.assertEqual(
                [d.id for d in registry.listed_definitions()],
                ["transformer"],
            )

    def test_retired_model_drops_from_active_and_listed(self):
        transformer = registry.get_definition("transformer")
        dash = registry.get_definition("dash")
        retired_dash = replace(dash, status=registry.STATUS_RETIRED)
        patched = (transformer, retired_dash)

        with patch.object(registry, "MODELS", patched):
            self.assertEqual(
                [d.id for d in registry.active_definitions()], ["transformer"]
            )
            self.assertEqual(
                [d.id for d in registry.listed_definitions()], ["transformer"]
            )

    def test_builtin_models_are_listed_and_ungated(self):
        for model_id in ("dash", "transformer"):
            with self.subTest(model=model_id):
                definition = registry.get_definition(model_id)
                self.assertTrue(definition.listed)
                self.assertFalse(definition.requires_credential)


class RedshiftInputPolicyTests(SimpleTestCase):
    """R13/R15/KD5: a three-way input policy, with the old boolean derived."""

    def test_builtin_policies_match_todays_semantics(self):
        dash = registry.get_definition("dash")
        transformer = registry.get_definition("transformer")
        self.assertEqual(dash.redshift_input, registry.REDSHIFT_INPUT_OPTIONAL)
        self.assertEqual(transformer.redshift_input, registry.REDSHIFT_INPUT_REQUIRED)
        # The derived property still answers exactly as the field used to.
        self.assertFalse(dash.requires_redshift)
        self.assertTrue(transformer.requires_redshift)

    def test_declining_redshift_is_not_requiring_it(self):
        dash = registry.get_definition("dash")
        no_redshift = replace(dash, redshift_input=registry.REDSHIFT_INPUT_NONE)
        self.assertFalse(no_redshift.requires_redshift)
        # R15: declining redshift as an input says nothing about estimating one.
        self.assertTrue(no_redshift.supports_redshift_estimation)


class GateConfigurationTests(SimpleTestCase):
    """R34/AE13: a gated model with unconfigured gate configuration fails closed."""

    def _gated_roster(self):
        transformer = registry.get_definition("transformer")
        dash = registry.get_definition("dash")
        gated = replace(dash, requires_credential=True, listed=False)
        return (transformer, gated)

    def _configured_env(self, **overrides):
        env = {
            gate_config.CREDENTIAL_ENV_VAR: "a-shared-credential",
            gate_config.LINK_TTL_ENV_VAR: "604800",
        }
        env.update(overrides)
        return env

    def test_missing_credential_is_rejected_naming_the_configuration(self):
        env = self._configured_env()
        del env[gate_config.CREDENTIAL_ENV_VAR]
        with patch.dict(os.environ, env, clear=True), override_settings(
            SECRET_KEY="a-real-signing-key"
        ):
            configuration = gate_config.gate_configuration()
        with self.assertRaises(ValueError) as ctx:
            registry.validate_gate_configuration(self._gated_roster(), configuration)
        self.assertIn(gate_config.CREDENTIAL_ENV_VAR, str(ctx.exception))

    def test_blank_credential_is_rejected(self):
        for blank in ("", "   ", "\t\n"):
            with self.subTest(credential=repr(blank)):
                env = self._configured_env(**{gate_config.CREDENTIAL_ENV_VAR: blank})
                with patch.dict(os.environ, env, clear=True), override_settings(
                    SECRET_KEY="a-real-signing-key"
                ):
                    configuration = gate_config.gate_configuration()
                with self.assertRaises(ValueError) as ctx:
                    registry.validate_gate_configuration(
                        self._gated_roster(), configuration
                    )
                self.assertIn(gate_config.CREDENTIAL_ENV_VAR, str(ctx.exception))

    def test_committed_default_signing_key_is_rejected(self):
        with patch.dict(
            os.environ, self._configured_env(), clear=True
        ), override_settings(SECRET_KEY="django-insecure-committed-default"):
            configuration = gate_config.gate_configuration()
        with self.assertRaises(ValueError) as ctx:
            registry.validate_gate_configuration(self._gated_roster(), configuration)
        self.assertIn(gate_config.SIGNING_KEY_NAME, str(ctx.exception))

    def test_missing_expiry_window_is_rejected(self):
        env = self._configured_env()
        del env[gate_config.LINK_TTL_ENV_VAR]
        with patch.dict(os.environ, env, clear=True), override_settings(
            SECRET_KEY="a-real-signing-key"
        ):
            configuration = gate_config.gate_configuration()
        with self.assertRaises(ValueError) as ctx:
            registry.validate_gate_configuration(self._gated_roster(), configuration)
        self.assertIn(gate_config.LINK_TTL_ENV_VAR, str(ctx.exception))

    def test_fully_configured_gate_passes(self):
        with patch.dict(
            os.environ, self._configured_env(), clear=True
        ), override_settings(SECRET_KEY="a-real-signing-key"):
            configuration = gate_config.gate_configuration()
        # Should not raise.
        registry.validate_gate_configuration(self._gated_roster(), configuration)

    def test_ungated_roster_passes_with_no_gate_configuration(self):
        with patch.dict(os.environ, {}, clear=True), override_settings(
            SECRET_KEY="django-insecure-committed-default"
        ):
            configuration = gate_config.gate_configuration()
        # Should not raise: nothing in the shipped roster is gated.
        registry.validate_gate_configuration(registry.MODELS, configuration)
