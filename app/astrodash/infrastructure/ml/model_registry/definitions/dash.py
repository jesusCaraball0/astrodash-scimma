"""The DASH built-in classifier definition."""

from astrodash.infrastructure.ml.classifiers.dash_classifier import DashClassifier
from astrodash.infrastructure.ml.model_registry._model_definition import (
    STATUS_ACTIVE,
    ModelDefinition,
)

DASH = ModelDefinition(
    id="dash",
    title="Dash Model",
    description="CNN-based model from the original DASH paper",
    color="#28a745",
    feature_tags=("CNN", "Template Matching", "RLap Scores"),
    icon="bi-flask",
    recommended=True,
    status=STATUS_ACTIVE,
    is_default=False,
    requires_redshift=False,
    preprocessing="dash",
    supports_twins=True,
    supports_redshift_estimation=True,
    supports_template_overlays=True,
    supports_rlap=True,
    classifier=DashClassifier,
)
