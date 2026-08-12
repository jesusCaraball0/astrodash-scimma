"""The registry of result surfaces and how each one presents itself.

A *result surface* is one tab in the classification result view, together with
the supporting routes that tab owns. Every model definition declares the
surfaces it offers as an ordered list of surface ids (see
:mod:`astrodash.infrastructure.ml.model_registry`); this module is the single
place an id is turned into something renderable -- its tab title, its pane
identity, and its routes.

The map lives here, in the web layer, rather than beside the definitions:
nothing under ``astrodash.infrastructure`` imports Django or knows about URL
names, so the definitions declare opaque ids and the registry's validator takes
the set of known ids as an argument (see :func:`known_surface_ids`, called from
the app-ready hook).

Pane identity is a separate field from the surface id because the classification
template's markup contract is rigid -- a tab is ``id="<slug>-tab"`` pointing at
``href="#<slug>-pane"`` -- and its slugs predate these ids (the DASH Twins
surface has always rendered as ``twins-tab`` / ``twins-pane``). Keeping the slug
separate lets an id be named for what it is without renaming markup.
"""

from dataclasses import dataclass
from typing import Dict, FrozenSet, Optional, Sequence, Tuple

from astrodash.infrastructure.ml.model_registry import (
    SURFACE_CLASSIFICATION,
    SURFACE_DASH_TWINS,
)


@dataclass(frozen=True)
class Surface:
    """One result surface: a tab in the classification result view.

    Attributes:
        id: Stable surface identifier, as declared by a model definition.
        title: Tab label as shown to the visitor (e.g. ``"DASH Twins"``).
        pane: Markup slug for the tab and its pane. The template renders
            ``id="<pane>-tab"``, ``href="#<pane>-pane"`` and
            ``aria-controls="<pane>-pane"`` from it.
        routes: Names of the supporting routes this surface owns, within the
            ``astrodash`` URL namespace. Empty when the surface renders inline
            in the classification view and owns no route of its own.
    """

    id: str
    title: str
    pane: str
    routes: Tuple[str, ...] = ()

    @property
    def tab_id(self) -> str:
        """DOM id of the tab anchor (``<pane>-tab``)."""
        return f"{self.pane}-tab"

    @property
    def pane_id(self) -> str:
        """DOM id of the tab pane (``<pane>-pane``), also its anchor target."""
        return f"{self.pane}-pane"


# Every known surface, keyed by id. Adding a surface is one entry here plus the
# id constant the definitions declare -- no per-model conditional in the
# classification template.
SURFACES: Dict[str, Surface] = {
    SURFACE_CLASSIFICATION: Surface(
        id=SURFACE_CLASSIFICATION,
        title="Classification",
        pane="classification",
        # The classification pane is rendered inline by the classify view
        # itself, so it owns no supporting route of its own.
        routes=(),
    ),
    SURFACE_DASH_TWINS: Surface(
        id=SURFACE_DASH_TWINS,
        title="DASH Twins",
        pane="twins",
        routes=("dash_twins", "dash_twins_data", "twins_search"),
    ),
}


def known_surface_ids() -> FrozenSet[str]:
    """Return the ids a model definition is allowed to declare.

    Returns:
        The set of every registered surface id. The app-ready hook passes this
        to the registry's surface validator, which cannot import this module.
    """
    return frozenset(SURFACES)


def get_surface(surface_id: str) -> Optional[Surface]:
    """Resolve a surface id to its presentation.

    Args:
        surface_id: The declared surface identifier to look up.

    Returns:
        The matching :class:`Surface`, or ``None`` if no surface has that id.
    """
    return SURFACES.get(surface_id)


def resolve_surfaces(surface_ids: Sequence[str]) -> Tuple[Surface, ...]:
    """Resolve a declared surface list, preserving its order.

    Args:
        surface_ids: The ordered surface ids a model definition declares.

    Returns:
        The matching :class:`Surface` entries in the declared order; the first
        is the surface that renders as the default tab.

    Raises:
        ValueError: If any id is not a known surface. Startup validation makes
            this unreachable for the shipped registry, so it means a caller
            passed something other than a validated declaration.
    """
    resolved = []
    for surface_id in surface_ids:
        surface = SURFACES.get(surface_id)
        if surface is None:
            raise ValueError(
                f"Unknown result surface id: '{surface_id}'. "
                f"Known surfaces: {sorted(SURFACES)}."
            )
        resolved.append(surface)
    return tuple(resolved)
