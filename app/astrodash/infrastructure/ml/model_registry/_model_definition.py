"""Core registry types: the model definition and lifecycle status constants.

This module holds the pieces every per-model definition file needs -- the
:class:`ModelDefinition` dataclass and the lifecycle status constants -- with no
dependency on the package root. Keeping them here (rather than in the package
``__init__``) lets each ``definitions/<id>.py`` import them without a circular
import against the package that assembles the registry.
"""

from dataclasses import dataclass, field
from typing import Optional, Tuple, Type

from astrodash.infrastructure.ml.classifiers.base import BaseClassifier

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
