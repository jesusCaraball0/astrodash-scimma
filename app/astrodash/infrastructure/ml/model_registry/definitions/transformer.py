"""The Transformer built-in classifier definition."""

from astrodash.infrastructure.ml.classifiers.transformer_classifier import (
    TransformerClassifier,
)
from astrodash.infrastructure.ml.model_registry._model_definition import (
    STATUS_ACTIVE,
    ModelDefinition,
)

TRANSFORMER = ModelDefinition(
    id="transformer",
    title="Transformer Model",
    description="Advanced transformer-based model with 5-class classification",
    color="#ff8c00",
    feature_tags=("Transformer", "5 Classes", "Fast Inference"),
    icon=None,
    recommended=False,
    status=STATUS_ACTIVE,
    is_default=True,
    requires_redshift=True,
    preprocessing="transformer",
    supports_twins=False,
    supports_redshift_estimation=False,
    supports_template_overlays=False,
    supports_rlap=False,
    classifier=TransformerClassifier,
)
