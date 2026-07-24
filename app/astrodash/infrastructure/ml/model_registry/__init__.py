"""Central declarative registry of the built-in classifier models.

This package is the single source of truth for the built-in classifiers (DASH
and Transformer). Each model is described once as a :class:`ModelDefinition` in
its own module under :mod:`.definitions`, carrying its UI card fields, lifecycle
status, default flag, capability and requirement flags, and a reference to the
classifier that runs it. Forms, the model-selection template, the classifier
factory, and the behavioral gates all read from here instead of scattering
``"dash"`` / ``"transformer"`` string literals across the codebase.

Adding a built-in model is one new ``definitions/<id>.py`` module plus a single
entry in ``MODELS`` here (and the model's ``config/settings.py`` paths and its
classifier). Retiring a model is a single ``status`` flip on its definition: a
retired model leaves the active surfaces (cards, form choices) but still
resolves its label and fields for any stored result that references it.

The registry is deliberately code-native. A data-driven or self-registering
registry for independently contributed models is a later runway, not built
here.
"""

from typing import Optional, Tuple

from astrodash.infrastructure.ml.model_registry._model_definition import (
    STATUS_ACTIVE,
    STATUS_RETIRED,
    ModelDefinition,
)
from astrodash.infrastructure.ml.model_registry.definitions.dash import DASH
from astrodash.infrastructure.ml.model_registry.definitions.transformer import (
    TRANSFORMER,
)

# Ordered registry of built-in classifiers. The order here is the order the
# cards render on the model-selection page (Transformer first, then DASH),
# preserving today's layout.
MODELS: Tuple[ModelDefinition, ...] = (
    TRANSFORMER,
    DASH,
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
