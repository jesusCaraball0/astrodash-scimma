"""Regression guards over the registry-driven model surface.

Three properties are enforced here, each of them a thing a later edit can undo
silently:

1. No model-defining ``model_type`` literal in the gate files -- now including
   the classification and batch templates and the access module, because a
   per-model conditional in a template is exactly as damaging as one in Python
   and the original scan could not see it.
2. Every route the surface map declares carries the access gate. The gate is a
   decorator and therefore opt-in: a surface added later could omit it and
   nothing would fail.
3. A view reachable in a scoped flow writes no session key outside the swept
   namespaces. Teardown sweeps the artifact prefix and the enumerated scope and
   selection keys; an artifact stored anywhere else survives a teardown that
   was never going to look for it.

Regression guard: no model-defining model_type literals in the gate files.

This refactor replaced the scattered ``model_type == 'dash'`` /
``== 'transformer'`` branches with reads against the model registry's
capability fields. Without a guard, a future edit can reintroduce exactly that
anti-pattern -- e.g. ``if model_type == 'dash':`` in the classify view -- and
the behavioral gate silently stops deriving from the registry again, defeating
the "one definition drives every gate" goal.

The guard scans the four gate files this refactor routed through the registry
and flags any conditional comparison of a value against a quoted built-in model
id. It intentionally does NOT scan the whole codebase: the REST API layer
(``views.py``), the separate template-handler factory
(``templates/template_factory.py``), and the docstrings/defaults that mention
``'dash'`` are out of this refactor's scope (see the plan's Scope Boundaries),
and flagging them would be dishonest about what was actually converted.

One comparison is exempt: the ``preprocessing == 'dash'`` /
``preprocessing == 'transformer'`` selection in
``spectrum_processing_service`` reads the definition's ``preprocessing``
identifier to pick a processor. Per the registry KTDs that identifier selects a
processor; it does not define a model, so it stays a string comparison.

Mirrors the ``test_no_version_literals.py`` precedent.
"""

import re
from pathlib import Path
from typing import List, Tuple

from django.test import SimpleTestCase, TestCase
from django.urls import resolve, reverse
from unittest.mock import patch

from astrodash.core import model_access
from astrodash.surfaces import SURFACES
from astrodash.tests.gate_fixtures import (
    GATE_CREDENTIAL,
    classify_post,
    gate_url,
    gated_gate,
    mocked_classification,
)

# app/ -- tests/ is app/astrodash/tests/, so parent.parent.parent is app/.
APP_ROOT = Path(__file__).resolve().parent.parent.parent

# The gate files routed through the model registry: the Python gates (U5) plus
# the two templates and the access module the surface and gate work added.
# Templates are scanned because a per-model conditional there is invisible to a
# Python-only scan, which is exactly where three of them used to live.
GATE_FILES = (
    "astrodash/forms.py",
    "astrodash/ui_views.py",
    "astrodash/core/model_access.py",
    "astrodash/domain/services/spectrum_processing_service.py",
    "astrodash/domain/services/redshift_service.py",
    "astrodash/templates/astrodash/classify.html",
    "astrodash/templates/astrodash/batch.html",
)

# Comment syntaxes a template can carry. Their contents are blanked before the
# scan, so a commented-out example does not trip the guard -- while keeping line
# numbers intact, so a real hit still reports where it is.
TEMPLATE_COMMENT_PATTERNS = (
    re.compile(r"<!--.*?-->", re.DOTALL),
    re.compile(r"\{#.*?#\}", re.DOTALL),
    re.compile(r"\{%\s*comment\s*.*?%\}.*?\{%\s*endcomment\s*%\}", re.DOTALL),
)

# A conditional comparison of a value against a quoted built-in model id, in
# either order (``x == 'dash'`` or ``'dash' == x``). The quote style is
# back-referenced so a mismatched-quote artifact cannot false-positive.
COMPARISON_PATTERN = re.compile(
    r"""(?:==|!=)\s*(?P<q1>['"])(?:dash|transformer)(?P=q1)"""
    r"""|(?P<q2>['"])(?:dash|transformer)(?P=q2)\s*(?:==|!=)"""
)


def _is_exempt(line: str) -> bool:
    """Return True for the exempted preprocessing-variant comparison.

    Args:
        line: The source line under inspection.

    Returns:
        True when the line is the ``preprocessing == ...`` processor-selection
        comparison, which reads a definition identifier rather than defining a
        model.
    """
    return "preprocessing ==" in line


def _strip_template_comments(text: str) -> str:
    """Blank out template comment bodies, preserving line structure.

    Args:
        text: The template source.

    Returns:
        The source with every comment's characters replaced by spaces and its
        newlines kept, so line numbers still line up with the file.
    """

    def blank(match: "re.Match[str]") -> str:
        return re.sub(r"[^\n]", " ", match.group(0))

    for pattern in TEMPLATE_COMMENT_PATTERNS:
        text = pattern.sub(blank, text)
    return text


def _scan_file(path: Path) -> List[Tuple[int, str]]:
    """Scan one file for model-defining model_type comparison literals.

    Args:
        path: The file to scan.

    Returns:
        A list of ``(lineno, line)`` tuples -- one per offending line. Empty
        when the file is clean.
    """
    hits: List[Tuple[int, str]] = []
    text = path.read_text(encoding="utf-8")
    if path.suffix == ".html":
        text = _strip_template_comments(text)
    for lineno, line in enumerate(text.splitlines(), start=1):
        if _is_exempt(line):
            continue
        if COMPARISON_PATTERN.search(line):
            hits.append((lineno, line))
    return hits


class NoModelTypeLiteralsTests(SimpleTestCase):
    """The gate files must not compare model_type against built-in id literals."""

    def test_gate_files_have_no_model_type_comparison_literals(self) -> None:
        offenders: List[str] = []
        for rel in GATE_FILES:
            path = APP_ROOT / rel
            for lineno, line in _scan_file(path):
                offenders.append(f"  {rel}:{lineno}: {line.strip()}")

        self.assertFalse(
            offenders,
            "Found model-defining model_type comparison literals in the gate "
            "files. Route behavioral gates through the model registry's "
            "capability fields (get_definition(model_type).<capability>) "
            "instead of comparing against 'dash'/'transformer':\n"
            + "\n".join(offenders),
        )


class GuardPatternsTests(SimpleTestCase):
    """Unit tests proving the guard FIRES on regressions and not on exemptions."""

    @staticmethod
    def _flags(line: str) -> bool:
        return not _is_exempt(line) and bool(COMPARISON_PATTERN.search(line))

    # --- positives: lines the guard MUST flag ---

    def test_flags_equality_against_dash(self) -> None:
        self.assertTrue(self._flags("        if model_type == 'dash':"))

    def test_flags_inequality_against_dash(self) -> None:
        self.assertTrue(self._flags('        if model_type != "dash":'))

    def test_flags_equality_against_transformer(self) -> None:
        self.assertTrue(self._flags("        if model == 'transformer' and z is None:"))

    def test_flags_reversed_comparison(self) -> None:
        self.assertTrue(self._flags("        if 'dash' == model_type:"))

    # --- negatives: lines the guard MUST NOT flag ---

    def test_does_not_flag_preprocessing_comparison(self) -> None:
        self.assertFalse(self._flags("            if preprocessing == 'dash':"))
        self.assertFalse(
            self._flags("            elif preprocessing == 'transformer':")
        )

    def test_does_not_flag_assignment_default(self) -> None:
        self.assertFalse(self._flags('        model_type: str = "dash"'))

    def test_does_not_flag_display_fallback_expression(self) -> None:
        self.assertFalse(
            self._flags(
                "            'modelType': model_type if model_type != 'user_uploaded' else 'dash',"
            )
        )

    def test_does_not_flag_docstring_mention(self) -> None:
        self.assertFalse(
            self._flags("            model_type: Type of model ('dash', 'transformer')")
        )

    # --- template comments: stripped before the scan ---

    def test_commented_out_literal_in_a_template_does_not_trip_the_guard(self) -> None:
        for comment in (
            "<!-- {% if model_type == 'dash' %} -->",
            "{# {% if model_type == 'dash' %} #}",
            "{% comment %}{% if model_type == 'dash' %}{% endcomment %}",
        ):
            stripped = _strip_template_comments(comment)
            self.assertFalse(
                COMPARISON_PATTERN.search(stripped),
                f"comment was not stripped: {comment}",
            )

    def test_a_live_template_literal_still_trips_the_guard(self) -> None:
        live = "{% if selected_model_type == 'dash' %}"
        self.assertTrue(COMPARISON_PATTERN.search(_strip_template_comments(live)))

    def test_comment_stripping_preserves_line_numbers(self) -> None:
        source = "a\n<!-- one\ntwo -->\n{% if model_type == 'dash' %}\n"
        stripped = _strip_template_comments(source)
        self.assertEqual(len(stripped.splitlines()), len(source.splitlines()))
        hit = [
            lineno
            for lineno, line in enumerate(stripped.splitlines(), start=1)
            if COMPARISON_PATTERN.search(line)
        ]
        self.assertEqual(hit, [4])


def _is_gated(view) -> bool:
    """Whether a view carries the model-access gate.

    Args:
        view: The resolved view callable.

    Returns:
        True when the gate decorator's marker is present. ``functools.wraps``
        copies it outward, so a decorator stacked above the gate does not hide
        it.
    """
    return getattr(view, "model_access_guarded", False) is True


class GateCoverageTests(SimpleTestCase):
    """R9: every route the surface map declares carries the gate.

    A decorator is opt-in by nature, so "a surface added later cannot silently
    omit the check" is only true if something checks. This is that something:
    it walks the surface map rather than a hand-written list, so registering a
    surface with an unguarded route fails here rather than in production.
    """

    def _guarded_route_names(self):
        """Return every route name that must carry the gate.

        Returns:
            list: The supporting routes of every registered surface, plus the
            classification view itself, which owns no supporting route but can
            run a model directly.
        """
        names = ["classify"]
        for surface in SURFACES.values():
            names.extend(surface.routes)
        return names

    def test_every_declared_surface_route_carries_the_gate(self) -> None:
        unguarded = []
        for name in self._guarded_route_names():
            view = resolve(reverse(f"astrodash:{name}")).func
            if not _is_gated(view):
                unguarded.append(name)
        self.assertFalse(
            unguarded,
            "These routes can run a model without consulting the access gate. "
            "Apply @model_access_required to each: " + ", ".join(unguarded),
        )

    def test_the_guard_would_flag_an_unguarded_view(self) -> None:
        def plain_view(request):  # pragma: no cover - never called
            return None

        self.assertFalse(_is_gated(plain_view))

    def test_the_guard_sees_through_a_stacked_decorator(self) -> None:
        # dash_twins carries @xframe_options_sameorigin above the gate; if the
        # marker did not survive that, this guard would be vacuously true.
        from astrodash import ui_views

        self.assertTrue(_is_gated(ui_views.dash_twins))


# Session keys the scoped flow may write: the scope, the selection, and the
# classification-artifact namespace teardown sweeps. Django owns the
# underscore-prefixed namespace (session expiry, auth, messages), which teardown
# deliberately leaves alone.
ALLOWED_SESSION_KEYS = (
    model_access.SCOPE_SESSION_KEYS + model_access.SELECTION_SESSION_KEYS
)


def _unsweepable_session_keys(session) -> List[str]:
    """Return session keys a teardown would leave behind.

    Args:
        session: The session (or any key-bearing mapping) to inspect.

    Returns:
        Every key that is neither Django's own, nor one teardown enumerates,
        nor inside the artifact prefix it sweeps.
    """
    return sorted(
        key
        for key in session.keys()
        if not key.startswith("_")
        and key not in ALLOWED_SESSION_KEYS
        and not key.startswith(model_access.ARTIFACT_KEY_PREFIX)
    )


class ScopedFlowSessionKeyTests(TestCase):
    """R33: nothing a scoped flow writes can escape the teardown sweep.

    The sweep already covers anything added under the artifact prefix, so the
    escape route is an artifact stored *outside* it, where the sweep will never
    reach. This drives the whole scoped flow and asserts no such key appears.
    """

    def _run_scoped_flow(self):
        """Redeem a link, classify, and browse the surfaces it declares."""
        with gated_gate(), patch.object(model_access, "_now", return_value=1000.0):
            token = model_access.mint_entry_link("dash")
            self.client.post(gate_url(token), data={"credential": GATE_CREDENTIAL})
        with gated_gate(), patch.object(
            model_access, "_now", return_value=1001.0
        ), mocked_classification("dash"):
            self.client.get(reverse("astrodash:classify"))
            self.client.post(reverse("astrodash:classify"), data=classify_post("dash"))
        with gated_gate(), patch.object(model_access, "_now", return_value=1002.0):
            self.client.get(reverse("astrodash:dash_twins"))

    def test_scoped_flow_writes_no_unsweepable_session_key(self) -> None:
        self._run_scoped_flow()
        self.assertEqual(_unsweepable_session_keys(self.client.session), [])

    def test_teardown_then_leaves_nothing_of_the_flow_behind(self) -> None:
        self._run_scoped_flow()
        with gated_gate(), patch.object(model_access, "_now", return_value=1003.0):
            self.client.post(reverse("astrodash:end_model_scope"))
        session = self.client.session
        self.assertEqual(
            [k for k in session.keys() if not k.startswith("_")],
            [],
        )

    def test_the_guard_would_flag_a_key_outside_the_swept_namespaces(self) -> None:
        self.assertEqual(
            _unsweepable_session_keys({"twins_embedding_cache": [1, 2, 3]}),
            ["twins_embedding_cache"],
        )

    def test_the_guard_accepts_the_keys_teardown_actually_sweeps(self) -> None:
        swept = {
            model_access.SCOPE_MODEL_KEY: "dash",
            model_access.SCOPE_DEADLINE_KEY: 1.0,
            "selected_model_type": "dash",
            "classify_results": {},
            "_session_expiry": 60,
        }
        self.assertEqual(_unsweepable_session_keys(swept), [])
