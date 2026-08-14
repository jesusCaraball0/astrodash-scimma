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

# Lifecycle status values. "active" models are offered for new use; "retired"
# models are hidden from new use but still resolve their label/fields.
# Whether a model is *listed* is a separate declaration (see ``listed`` below).
STATUS_ACTIVE = "active"
STATUS_RETIRED = "retired"

# Redshift input policies. A model declares redshift as a required input, an
# optional input, or not an input at all. This is independent of whether the
# model *estimates* a redshift as an output (``supports_redshift_estimation``).
REDSHIFT_INPUT_REQUIRED = "required"
REDSHIFT_INPUT_OPTIONAL = "optional"
REDSHIFT_INPUT_NONE = "none"

# Result surface ids. A definition declares these as opaque identifiers; how a
# surface presents itself (tab title, pane markup, supporting routes) is
# web-layer knowledge and lives in ``astrodash.surfaces``, because nothing here
# imports Django or knows about URL names. Every definition must declare
# :data:`SURFACE_CLASSIFICATION` -- a model that classifies always has a
# classification result to show.
SURFACE_CLASSIFICATION = "classification"
SURFACE_DASH_TWINS = "dash_twins"


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
        listed: Whether the model is offered on the selection surfaces (cards,
            form choice controls). Listing is presentation only and never
            access control: an unlisted model that requires no credential
            stays reachable by anyone who names it. A gated model is always
            unlisted, and the active default is always listed.
        is_default: Whether this is the default selected model. Exactly one
            active definition must be the default.
        requires_credential: Whether running the model requires the shared
            credential, reached only through a model-scoped entry link. Implies
            ``listed`` is ``False``.
        redshift_input: Redshift input policy -- one of
            :data:`REDSHIFT_INPUT_REQUIRED`, :data:`REDSHIFT_INPUT_OPTIONAL`,
            or :data:`REDSHIFT_INPUT_NONE`. Drives the classify-form and
            batch-view validation gates and whether the redshift controls
            render at all.
        preprocessing: Identifier of the preprocessing variant this model needs,
            consumed by the spectrum processing service (e.g. ``"dash"``).
        surfaces: Ordered ids of the result surfaces this model offers, the
            first being the default tab. Only declared surfaces render, in this
            order. The ids are opaque here and resolved through the web layer's
            surface map; the list must be non-empty and must include
            :data:`SURFACE_CLASSIFICATION`.
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
    listed: bool
    is_default: bool
    requires_credential: bool
    redshift_input: str
    preprocessing: str
    surfaces: Tuple[str, ...]
    supports_redshift_estimation: bool
    supports_template_overlays: bool
    supports_rlap: bool
    classifier: Type[BaseClassifier] = field(compare=False)

    @property
    def is_active(self) -> bool:
        """Whether the model is currently active (not retired)."""
        return self.status == STATUS_ACTIVE
