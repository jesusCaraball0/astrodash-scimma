"""Entry links, the shared credential, and the model-scoped session.

A model definition can declare that running it requires a shared credential
(``requires_credential``). Such a model is reachable only by redeeming a
*model-scoped entry link* -- a signed token naming one model and carrying an
absolute deadline -- and then presenting the credential. A correct credential
establishes a *scope*: a session locked to that one model, which expires no
later than the link that created it.

This module owns the mechanism; the views own the pages. It is deliberately
small, because the gate is interim: it exists only because no identity layer is
applied to the AstroDash views today, and the identity-and-access work retires
it when that work lands.

Three properties are load-bearing and each is easy to get subtly wrong:

* **The deadline is stamped at mint, not evaluated later.** The token carries an
  absolute expiry rather than being checked against the currently configured
  window, so shortening that window cannot retroactively move an outstanding
  link's deadline (nor lengthening it extend one).
* **The scope carries that same absolute deadline in the session.** Django's
  ``set_expiry`` treats an integer as *seconds of inactivity* and re-arms on
  every session write -- and the classify flow writes on every submit -- so it
  bounds idleness, not lifetime. It is kept only as a secondary bound; the
  stored deadline is what the gate checks.
* **Teardown deletes named keys and never calls ``flush()``.** The session is
  shared with Django's auth framework, so flushing would log out an
  authenticated visitor. Three key categories are swept: the scope keys, the
  selection keys, and everything under the classification-artifact prefix.
"""

import hmac
import time
from dataclasses import dataclass
from functools import wraps
from typing import Optional

from django.contrib import messages
from django.core import signing
from django.http import HttpResponseRedirect, JsonResponse
from django.shortcuts import render
from django.urls import reverse

from astrodash.core.gate_config import (
    CREDENTIAL_ENV_VAR,
    LINK_TTL_ENV_VAR,
    SIGNING_KEY_NAME,
    gate_configuration,
)
from astrodash.infrastructure.ml.model_registry import get_definition
from astrodash.surfaces import offers_route

# Salt distinct to this purpose, so a token minted here cannot be replayed
# against any other signed value the project produces.
ENTRY_LINK_SALT = "astrodash.model-access.entry-link"

# Session keys holding the scope: the one model it names, and the absolute
# deadline (a POSIX timestamp) it must not outlive.
SCOPE_MODEL_KEY = "model_scope_model_type"
SCOPE_DEADLINE_KEY = "model_scope_deadline"
SCOPE_SESSION_KEYS = (SCOPE_MODEL_KEY, SCOPE_DEADLINE_KEY)

# Session keys holding an ordinary (unscoped) model selection. Teardown clears
# these too: a scope that left a prior selection standing is how a scope ends up
# running a model it does not name.
SELECTION_SESSION_KEYS = ("selected_model_type", "selected_model_id")

# Every session key a classification writes is prefixed with this, which makes
# the artifact namespace sweepable: anything added under it is torn down without
# being enumerated here.
ARTIFACT_KEY_PREFIX = "classify_"


class GateNotConfigured(RuntimeError):
    """Raised when the gate is used while its deployment values are missing.

    Startup validation makes this unreachable for a deployment whose roster
    contains a gated model, so it means the gate was driven in an environment
    that never intended to serve one.
    """


class EntryLinkRefused(Exception):
    """Raised for any entry link that does not grant access.

    One exception covers tampering, a malformed payload, and a lapsed deadline
    alike, because the refusal must disclose nothing about which models exist:
    the caller cannot tell the cases apart, so it cannot leak them.
    """


@dataclass(frozen=True)
class EntryLink:
    """A redeemed entry link.

    Attributes:
        model_id: The one model the link names.
        expires_at: Absolute POSIX timestamp the link -- and any scope it
            establishes -- expires at.
    """

    model_id: str
    expires_at: float


def _now() -> float:
    """Return the current time as a POSIX timestamp.

    Indirection so tests can move time without touching the clock.

    Returns:
        The current POSIX timestamp.
    """
    return time.time()


def _require(name: str) -> str:
    """Read one normalized gate configuration value, or fail closed.

    Args:
        name: The configuration name, as an operator sets it.

    Returns:
        The configured value.

    Raises:
        GateNotConfigured: If the value is unset, blank, or left at a committed
            default.
    """
    value = gate_configuration().get(name)
    if value is None:
        raise GateNotConfigured(
            f"The model access gate is not configured: {name} is unset, empty, "
            "or left at a committed default."
        )
    return value


def link_ttl_seconds() -> int:
    """Return the configured entry-link expiry window, in seconds.

    Returns:
        The window as a positive integer.

    Raises:
        GateNotConfigured: If the window is unconfigured.
    """
    return int(_require(LINK_TTL_ENV_VAR))


def mint_entry_link(model_id: str, ttl_seconds: Optional[int] = None) -> str:
    """Mint a signed entry-link token for one model.

    The deadline is computed once, here, and travels inside the token, so the
    link's lifetime is fixed at mint rather than re-derived at redemption.

    Args:
        model_id: The model the link grants access to.
        ttl_seconds: Optional window override, in seconds; the configured
            window is used when omitted.

    Returns:
        The signed token, to be placed in the entry-link path.

    Raises:
        GateNotConfigured: If the signing key or (absent an override) the
            window is unconfigured.
    """
    window = link_ttl_seconds() if ttl_seconds is None else int(ttl_seconds)
    payload = {"model": model_id, "expires_at": _now() + window}
    return signing.dumps(payload, key=_require(SIGNING_KEY_NAME), salt=ENTRY_LINK_SALT)


def redeem_entry_link(token: str) -> EntryLink:
    """Resolve an entry-link token, refusing anything that does not grant access.

    The token is not loaded with a ``max_age``: the deadline it carries was
    stamped at mint and is authoritative, so re-deriving one from the currently
    configured window would let a configuration change move an outstanding
    link's deadline. ``SignatureExpired`` subclasses ``BadSignature``, so the
    single catch below covers it however the token was produced.

    Args:
        token: The signed token from the entry-link path.

    Returns:
        The resolved :class:`EntryLink`.

    Raises:
        EntryLinkRefused: If the token is malformed, signed with another key,
            tampered with, or past its deadline.
        GateNotConfigured: If the signing key is unconfigured.
    """
    key = _require(SIGNING_KEY_NAME)
    try:
        payload = signing.loads(token, key=key, salt=ENTRY_LINK_SALT)
    except signing.BadSignature as exc:
        raise EntryLinkRefused("Entry link is not valid.") from exc

    model_id = payload.get("model") if isinstance(payload, dict) else None
    expires_at = payload.get("expires_at") if isinstance(payload, dict) else None
    if not model_id or not isinstance(expires_at, (int, float)):
        raise EntryLinkRefused("Entry link is not valid.")

    if _now() >= expires_at:
        raise EntryLinkRefused("Entry link is not valid.")

    return EntryLink(model_id=model_id, expires_at=float(expires_at))


def credential_matches(submitted: Optional[str]) -> bool:
    """Compare a submitted credential against the configured one, in constant time.

    Args:
        submitted: The credential as posted, or ``None`` when absent.

    Returns:
        True when it matches the configured shared credential.

    Raises:
        GateNotConfigured: If no credential is configured.
    """
    expected = _require(CREDENTIAL_ENV_VAR)
    return hmac.compare_digest(str(submitted or ""), expected)


def end_scope(session) -> None:
    """Clear the scope, any model selection, and every classification artifact.

    Never calls ``flush()``: the session is shared with Django's auth
    framework, so flushing would log out an authenticated visitor along with
    ending the scope. Both redemption and the explicit end call this, which is
    why a prior *selection* is swept as well -- leaving one standing is how a
    scope ends up running a model it does not name.

    Args:
        session: The request's session.
    """
    for key in SCOPE_SESSION_KEYS + SELECTION_SESSION_KEYS:
        session.pop(key, None)
    for key in [k for k in list(session.keys()) if k.startswith(ARTIFACT_KEY_PREFIX)]:
        session.pop(key, None)
    session.modified = True


def begin_scope(session, link: EntryLink) -> None:
    """Establish a session scoped to one model, bounded by its link's deadline.

    Any prior scope, selection, and classification artifact is cleared first,
    so the scope is written over a clean session rather than beside stale
    state.

    The scoped model is also written as the session's selection, so every
    surface that already reads a selection sees the scoped model; the scope
    keys remain the authority, and the gate resolves them first.

    Args:
        session: The request's session.
        link: The redeemed entry link that grants the scope.
    """
    end_scope(session)
    session[SCOPE_MODEL_KEY] = link.model_id
    session[SCOPE_DEADLINE_KEY] = link.expires_at
    session["selected_model_type"] = link.model_id

    # Secondary bound only: Django re-arms this on every session write, so it
    # caps idleness rather than lifetime. The stored deadline above is what the
    # gate enforces.
    remaining = int(max(0, link.expires_at - _now()))
    session.set_expiry(remaining)


def scope_model_id(session) -> Optional[str]:
    """Return the model a session is scoped to, ignoring its deadline.

    Args:
        session: The request's session.

    Returns:
        The scoped model id, or ``None`` when the session holds no scope.
    """
    return session.get(SCOPE_MODEL_KEY)


def scope_expired(session) -> bool:
    """Whether a session's scope has passed the deadline it was granted with.

    Args:
        session: The request's session.

    Returns:
        True when a scope is present and its stored deadline has passed. A
        scope with no stored deadline is treated as expired: it cannot be
        proven to be within one.
    """
    if not scope_model_id(session):
        return False
    deadline = session.get(SCOPE_DEADLINE_KEY)
    if not isinstance(deadline, (int, float)):
        return True
    return _now() >= deadline


def live_scope_model_id(session) -> Optional[str]:
    """Return the scoped model only while the scope is still within its deadline.

    Args:
        session: The request's session.

    Returns:
        The scoped model id, or ``None`` when there is no scope or it has
        lapsed.
    """
    if scope_expired(session):
        return None
    return scope_model_id(session)


def effective_model_id(session) -> Optional[str]:
    """Return the model a request will actually run.

    The scope wins over a session selection (KTD10): a scoped visitor runs the
    scoped model whatever else the session -- or the submitted form -- says.

    Args:
        session: The request's session.

    Returns:
        The scoped model id while a live scope exists, otherwise the session's
        model selection, otherwise ``None``.
    """
    return live_scope_model_id(session) or session.get("selected_model_type")


# Copy for the two page-level refusals. The lapse case may name that the window
# ended, because its visitor already knows which model they were using; the cold
# case must not, because its visitor may not.
SCOPE_LAPSED_HEADING = "This review window has ended"
SCOPE_LAPSED_MESSAGE = (
    "The access link that opened this session has expired, so the session has "
    "ended and everything it produced has been discarded. If you still need "
    "access, ask whoever sent you the link for a new one."
)

# Refusal shown when a surface is requested for a model that does not declare
# it. Unchanged from the guard this decorator absorbed.
SURFACE_NOT_OFFERED_MESSAGE = "This result surface is not offered for this model."

# Refusal shown when a gated model is reached without a scope: it is reachable
# only through an entry link, so the visitor is returned to the public picker.
GATED_WITHOUT_SCOPE_MESSAGE = (
    "That model is not available. Please choose a model to continue."
)


# Why a guarded request was refused. The gate evaluates in a fixed order --
# deadline, scope present, model selectable, surface declared -- because the
# order decides what a refused visitor learns.
REFUSED_SCOPE_LAPSED = "scope_lapsed"
REFUSED_GATED_WITHOUT_SCOPE = "gated_without_scope"
REFUSED_SURFACE_NOT_OFFERED = "surface_not_offered"


def _refusal_for(request, reason, as_json):
    """Build the response for a refused request.

    Args:
        request: The current request.
        reason: One of the ``REFUSED_*`` reasons.
        as_json: Whether the caller is a JSON route.

    Returns:
        HttpResponse: The refusal.
    """
    if reason == REFUSED_SCOPE_LAPSED:
        if as_json:
            return JsonResponse({"error": SCOPE_LAPSED_MESSAGE}, status=403)
        return render(
            request,
            "astrodash/model_gate_refused.html",
            {
                "refusal_heading": SCOPE_LAPSED_HEADING,
                "refusal_message": SCOPE_LAPSED_MESSAGE,
            },
            status=403,
        )

    if reason == REFUSED_GATED_WITHOUT_SCOPE:
        if as_json:
            return JsonResponse({"error": SURFACE_NOT_OFFERED_MESSAGE}, status=403)
        if request.path == reverse("astrodash:classify"):
            # The classification page is the one an ordinary visitor can land on
            # with a stale selection, so it is returned to the picker rather
            # than shown an error page.
            messages.error(request, GATED_WITHOUT_SCOPE_MESSAGE)
            return HttpResponseRedirect(
                reverse("astrodash:model_selection") + "?action=classify"
            )
        return render(
            request,
            "astrodash/model_gate_refused.html",
            {"refusal_heading": None, "refusal_message": None},
            status=403,
        )

    if as_json:
        return JsonResponse({"error": SURFACE_NOT_OFFERED_MESSAGE}, status=403)
    return render(
        request,
        "astrodash/model_gate_refused.html",
        {
            "refusal_heading": "This view is not available",
            "refusal_message": SURFACE_NOT_OFFERED_MESSAGE,
        },
        status=403,
    )


# Shown when a scoped session asks for a flow the scope does not admit. It
# points at the end action rather than simply refusing, because the visitor's
# way out is to end the scope, not to navigate away.
SCOPED_FLOW_UNAVAILABLE_MESSAGE = (
    "This session is limited to one model, so only classification is "
    "available. End the session to return to the model picker."
)

# Shown when a session's stored model is no longer one a visitor may select.
MODEL_NO_LONGER_SELECTABLE_MESSAGE = (
    "The model this session had selected is no longer available. Please choose "
    "a model to continue."
)


def clear_selection(session) -> None:
    """Drop a model selection the session may no longer use.

    Args:
        session: The request's session.
    """
    for key in SELECTION_SESSION_KEYS:
        session.pop(key, None)
    session.modified = True


def scoped_flow_refusal(request, action="classify"):
    """Refuse a flow a scoped session may not enter, or let it through.

    A scope reaches classification only, so the batch flow and the selection
    page -- both its rendered page and its POST handler -- are refused for a
    scoped visitor and pointed back at the classification page, where the
    explicit end action lives.

    Args:
        request: The current request.
        action: The selection action this flow belongs to, used when a lapsed
            scope has to send the visitor back to the picker.

    Returns:
        HttpResponse: The refusal, or ``None`` when the request may proceed.
    """
    if scope_model_id(request.session) and scope_expired(request.session):
        end_scope(request.session)
        return _refusal_for(request, REFUSED_SCOPE_LAPSED, as_json=False)

    if live_scope_model_id(request.session) is not None:
        messages.error(request, SCOPED_FLOW_UNAVAILABLE_MESSAGE)
        return HttpResponseRedirect(reverse("astrodash:classify"))

    return None


def revalidate_session_model(request, action="classify"):
    """Re-check the session's model on entry to a flow, per R35.

    Two things can have changed under a session since it last ran: its model
    may have been published (dissolving a scope that no longer has anything to
    guard), or it may have become gated, unlisted, or retired (making a public
    session's selection unusable). Both are settled here, on entry, rather than
    being discovered halfway through a classification.

    Only ids the registry resolves are revalidated: a user-uploaded selection
    passes through untouched, or every uploaded-model visitor would be bounced
    to the picker.

    Args:
        request: The current request.
        action: The selection action to return to, ``"classify"`` or
            ``"batch"``.

    Returns:
        HttpResponse: A redirect to the selection page when the session's model
        is no longer selectable, or ``None`` when the request may proceed.
    """
    scoped = scope_model_id(request.session)
    if scoped:
        definition = get_definition(scoped)
        if definition is not None and not definition.requires_credential:
            # Published: there is nothing left to scope, so the scope dissolves
            # into an ordinary selection of the same model.
            end_scope(request.session)
            request.session["selected_model_type"] = scoped
        return None

    selected = request.session.get("selected_model_type")
    definition = get_definition(selected) if selected else None
    if definition is None:
        return None

    if (
        definition.requires_credential
        or not definition.listed
        or not definition.is_active
    ):
        clear_selection(request.session)
        messages.error(request, MODEL_NO_LONGER_SELECTABLE_MESSAGE)
        return HttpResponseRedirect(
            reverse("astrodash:model_selection") + f"?action={action}"
        )

    return None


def evaluate_access(session, model_id, route_name):
    """Decide whether a guarded request may proceed.

    Checks run in a fixed order -- deadline, then scope presence, then whether
    the model is reachable at all, then whether it declares the surface -- so a
    refusal cannot leak by ordering.

    Args:
        session: The request's session. A lapsed scope is torn down here, so
            nothing it produced stays reachable.
        model_id: The model that authorizes this request (see
            :func:`astrodash.surfaces.declared_surfaces`).
        route_name: The supporting route's name, or ``None`` for the
            classification view itself, which owns no supporting route.

    Returns:
        One of the ``REFUSED_*`` reasons, or ``None`` when the request may
        proceed.
    """
    if scope_model_id(session) and scope_expired(session):
        end_scope(session)
        return REFUSED_SCOPE_LAPSED

    if live_scope_model_id(session) is None:
        definition = get_definition(model_id) if model_id else None
        if definition is not None and definition.requires_credential:
            return REFUSED_GATED_WITHOUT_SCOPE

    if route_name and not offers_route(model_id, route_name):
        return REFUSED_SURFACE_NOT_OFFERED

    return None


def model_access_required(route_name=None, *, from_classified=False, as_json=False):
    """Guard a view that can run a model, consulting the scope on every request.

    A decorator rather than middleware (KTD1): the only hand-rolled gate this
    codebase has is the interim API-writes decorator, there is no
    project-authored Django middleware at all, and Django reserves middleware
    for whole-app defaults. Because a decorator is opt-in by nature, a guard
    test walks every route the surface map declares and asserts this is applied.

    Args:
        route_name: The name of the supporting route being guarded, or ``None``
            for the classification view itself.
        from_classified: Whether the route authorizes from the *classified*
            model rather than the selected one (KTD5). True only for a route
            that consumes a classification artifact; a route serving a
            model-agnostic payload authorizes from the selection, so it stays
            browsable before any classification, exactly as today.
        as_json: Whether refusals should be JSON rather than a rendered page.

    Returns:
        The view decorator.
    """

    def decorate(view_func):
        @wraps(view_func)
        def wrapper(request, *args, **kwargs):
            if from_classified:
                model_id = request.session.get("classify_model_type")
            else:
                model_id = effective_model_id(request.session)
            reason = evaluate_access(request.session, model_id, route_name)
            if reason is not None:
                if reason == REFUSED_GATED_WITHOUT_SCOPE and not from_classified:
                    # The selection that pointed here is no longer one a visitor
                    # may hold, so turning them away drops it too -- otherwise
                    # the picker they land on still carries the stale pointer.
                    clear_selection(request.session)
                return _refusal_for(request, reason, as_json)
            return view_func(request, *args, **kwargs)

        # Marker the coverage guard reads. A decorator is opt-in by nature, so a
        # surface added later could silently omit the gate; the guard walks every
        # route the surface map declares and asserts this attribute is present.
        # ``functools.wraps`` copies it outward, so an additional decorator
        # stacked above this one does not hide it.
        wrapper.model_access_guarded = True
        return wrapper

    return decorate
