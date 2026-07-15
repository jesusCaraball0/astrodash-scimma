"""Unit tests for the registry-driven classifier factory and form choices (U3).

The factory tests are hermetic: they never load real model weights. Built-in
resolution is checked by patching the registry lookup (the factory wiring) and,
separately, by asserting the real registry maps each built-in id to its
classifier class. The user-model bypass is checked with the storage and
classifier patched out.
"""

from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase

from astrodash.core.exceptions import ModelConfigurationException
from astrodash.forms import ClassifyForm, ModelSelectionForm
from astrodash.infrastructure.ml import model_registry as registry
from astrodash.infrastructure.ml.classifiers.dash_classifier import DashClassifier
from astrodash.infrastructure.ml.classifiers.transformer_classifier import (
    TransformerClassifier,
)
from astrodash.infrastructure.ml.model_factory import ModelFactory


class FactoryResolutionTests(SimpleTestCase):
    def test_builtin_resolves_and_instantiates_with_config(self):
        fake_cls = MagicMock(return_value="INSTANCE")
        fake_def = MagicMock(classifier=fake_cls)
        config = object()
        with patch(
            "astrodash.infrastructure.ml.model_factory.get_definition",
            return_value=fake_def,
        ):
            result = ModelFactory(config).get_classifier("dash")
        fake_cls.assert_called_once_with(config)
        self.assertEqual(result, "INSTANCE")

    def test_real_registry_maps_builtins_to_their_classifiers(self):
        self.assertIs(registry.get_definition("dash").classifier, DashClassifier)
        self.assertIs(
            registry.get_definition("transformer").classifier, TransformerClassifier
        )

    def test_unknown_model_type_raises(self):
        with self.assertRaises(ModelConfigurationException):
            ModelFactory().get_classifier("bogus")

    def test_user_model_id_bypasses_registry(self):
        with patch("astrodash.infrastructure.ml.model_factory.ModelStorage"), patch(
            "astrodash.infrastructure.ml.model_factory.UserClassifier",
            return_value="USER_INSTANCE",
        ) as user_cls, patch(
            "astrodash.infrastructure.ml.model_factory.get_definition"
        ) as get_def:
            # Even with a built-in model_type, a user_model_id takes precedence
            # and the registry is never consulted.
            result = ModelFactory().get_classifier("dash", user_model_id="abc")
        user_cls.assert_called_once()
        get_def.assert_not_called()
        self.assertEqual(result, "USER_INSTANCE")


class FormChoiceTests(SimpleTestCase):
    def test_classify_form_choices_and_default(self):
        form = ClassifyForm()
        self.assertEqual(
            list(form.fields["model"].choices),
            [
                ("transformer", "Transformer Model"),
                ("dash", "Dash Model"),
                ("user_uploaded", "User uploaded model"),
            ],
        )
        self.assertEqual(form.fields["model"].initial, "transformer")

    def test_selection_form_choices(self):
        form = ModelSelectionForm()
        self.assertEqual(
            list(form.fields["model_type"].choices),
            [
                ("transformer", "Transformer Model"),
                ("dash", "Dash Model"),
                ("user_model", "Use Uploaded Model"),
                ("upload", "Upload Your Model"),
            ],
        )
