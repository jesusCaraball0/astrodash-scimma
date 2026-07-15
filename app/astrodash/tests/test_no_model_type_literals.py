"""Regression guard: no model-defining model_type literals in the gate files.

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

from django.test import SimpleTestCase

# app/ -- tests/ is app/astrodash/tests/, so parent.parent.parent is app/.
APP_ROOT = Path(__file__).resolve().parent.parent.parent

# The gate files this refactor routed through the model registry (U5).
GATE_FILES = (
    "astrodash/forms.py",
    "astrodash/ui_views.py",
    "astrodash/domain/services/spectrum_processing_service.py",
    "astrodash/domain/services/redshift_service.py",
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
