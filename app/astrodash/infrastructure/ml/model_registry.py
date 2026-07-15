"""Central declarative registry of the built-in classifier models.

This module is the single source of truth for the built-in classifiers (DASH
and Transformer). Each model is described once as a :class:`ModelDefinition`
carrying its UI card fields, lifecycle status, default flag, capability and
requirement flags, and a reference to the classifier that runs it. Forms, the
model-selection template, the classifier factory, and the behavioral gates all
read from here instead of scattering ``"dash"`` / ``"transformer"`` string
literals across the codebase.

Adding a built-in model is one new :class:`ModelDefinition` in ``MODELS`` plus
its classifier (and its ``config/settings.py`` paths). Retiring a model is a
single ``status`` flip on its definition: a retired model leaves the active
surfaces (cards, form choices) but still resolves its label and fields for any
stored result that references it.

The registry is deliberately code-native. A data-driven or self-registering
registry for independently contributed models is a later runway, not built
here.
"""

from dataclasses import dataclass, field
from typing import Optional, Tuple, Type

from astrodash.infrastructure.ml.classifiers.base import BaseClassifier
from astrodash.infrastructure.ml.classifiers.dash_classifier import DashClassifier
from astrodash.infrastructure.ml.classifiers.transformer_classifier import (
    TransformerClassifier,
)

# Lifecycle status values. "active" models appear on the selection surfaces;
# "retired" models are hidden from new use but still resolve their label/fields.
STATUS_ACTIVE = "active"
STATUS_RETIRED = "retired"


@dataclass(frozen=True)
class ModelDefinition:
    """A single built-in classifier model, described once.

    Attributes:
        id: Stable identifier, also the ``model_type`` value stored on results
            and passed to the factory (e.g. ``"dash"``, ``"transformer"``).
        title: Card title as shown on the model-selection page.
        description: Card description text.
        color: Hex accent color for the card badges and selected-state border.
        feature_tags: Ordered feature-tag labels rendered as badges on the card.
        icon: Optional Bootstrap icon class for the card (e.g. ``"bi-flask"``);
            ``None`` for models with no icon.
        recommended: Whether the card shows the RECOMMENDED badge.
        status: Lifecycle status, :data:`STATUS_ACTIVE` or :data:`STATUS_RETIRED`.
        is_default: Whether this is the default selected model. Exactly one
            active definition must be the default.
        requires_redshift: Whether a redshift is required to classify with this
            model (drives the classify-form and batch-view validation gates).
        preprocessing: Identifier of the preprocessing variant this model needs,
            consumed by the spectrum processing service (e.g. ``"dash"``).
        supports_twins: Whether a classification with this model can seed the
            FIND TWINS embedding search.
        supports_redshift_estimation: Whether template-based redshift estimation
            is offered for this model.
        supports_template_overlays: Whether the result view offers the template
            overlay section for this model.
        supports_rlap: Whether batch results populate RLap scores for this model.
        classifier: The :class:`BaseClassifier` subclass that runs this model;
            the factory instantiates it with the ML config.
    """

    id: str
    title: str
    description: str
    color: str
    feature_tags: Tuple[str, ...]
    icon: Optional[str]
    recommended: bool
    status: str
    is_default: bool
    requires_redshift: bool
    preprocessing: str
    supports_twins: bool
    supports_redshift_estimation: bool
    supports_template_overlays: bool
    supports_rlap: bool
    classifier: Type[BaseClassifier] = field(compare=False)

    @property
    def is_active(self) -> bool:
        """Whether the model is currently active (not retired)."""
        return self.status == STATUS_ACTIVE


# Ordered registry of built-in classifiers. The order here is the order the
# cards render on the model-selection page (Transformer first, then DASH),
# preserving today's layout.
MODELS: Tuple[ModelDefinition, ...] = (
    ModelDefinition(
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
    ),
    ModelDefinition(
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
    ),
)


def validate_registry(models: Tuple[ModelDefinition, ...]) -> None:
    """Validate registry invariants.

    Args:
        models: The collection of model definitions to validate.

    Raises:
        ValueError: If model ids are not unique, or if the number of active
            definitions marked as default is not exactly one.
    """
    ids = [m.id for m in models]
    if len(ids) != len(set(ids)):
        raise ValueError(f"Duplicate model ids in registry: {ids}")

    active_defaults = [m for m in models if m.is_active and m.is_default]
    if len(active_defaults) != 1:
        raise ValueError(
            "Exactly one active model must be the default; "
            f"found {len(active_defaults)}: {[m.id for m in active_defaults]}"
        )


def get_definition(model_id: str) -> Optional[ModelDefinition]:
    """Resolve a model id to its definition, active or retired.

    Args:
        model_id: The model identifier (``model_type``) to look up.

    Returns:
        The matching :class:`ModelDefinition`, or ``None`` if no built-in model
        has that id (e.g. a user-uploaded model type), so callers can fall back
        to their non-built-in behavior.
    """
    for definition in MODELS:
        if definition.id == model_id:
            return definition
    return None


def active_definitions() -> Tuple[ModelDefinition, ...]:
    """Return the active model definitions in registry order.

    Returns:
        The definitions whose status is :data:`STATUS_ACTIVE`, in the order they
        appear in ``MODELS``.
    """
    return tuple(m for m in MODELS if m.is_active)


def default_definition() -> ModelDefinition:
    """Return the default active model definition.

    Returns:
        The single active definition marked as the default.

    Raises:
        ValueError: If the exactly-one-active-default invariant does not hold.
    """
    defaults = [m for m in MODELS if m.is_active and m.is_default]
    if len(defaults) != 1:
        raise ValueError(
            "Exactly one active model must be the default; " f"found {len(defaults)}"
        )
    return defaults[0]


# Enforce the registry invariants at import time.
validate_registry(MODELS)
