"""Regression guard: no hardcoded version literals in production source.

Without this guard, a future change can reintroduce the exact bug R5
exists to prevent — e.g. ``__version__ = "1.2.3"`` in a new module, or
``APP_VERSION = "1.2.3"`` re-hardcoded — and the displayed footer
silently drifts from the deployed image tag again.

The scan excludes tests/, migrations/, and __pycache__/ — version
references in auto-generated migrations are legitimate, and test
fixtures may need version-shaped strings for their own purposes.

Pattern (a) — the assignment check — fires when ``__version__`` or
``APP_VERSION`` is assigned a quoted version literal. The right-hand
side must be a quoted semver (optionally ``v``-prefixed), not a
function call — so the legitimate ``APP_VERSION = resolve_app_version()``
in settings.py and the log format string ``"APP_VERSION=%s"`` in
apps.py both pass.

Pattern (b) (three-segment semver) only fires on lines that contain a
**quoted** semver AND the case-insensitive keyword ``version``. The
plan prescribed a bare-semver-plus-keyword rule, but a dry run against
the codebase surfaced a false positive — the unquoted ``1.9.0`` in
``# InconsistentVersionWarning`` comments contains ``Version`` as a
substring of the warning class name, so the keyword filter alone is
insufficient. Requiring the semver to be quoted preserves the plan's
intent — catch ``APP_VERSION = "v1.0.0"``, ``"version": "x.y.z"``, and
``dev2-v1.1.0``-shaped tags while passing over the ``Django 3.2.9``
docstring in settings.py, the ``'127.0.0.1'`` IP literal in the same
file, and the sklearn / numba / umap-learn dependency version comments
in twins_search_service.py. The ``v?`` prefix on the semver pattern is
defence in depth — the chart emits ``v``-prefixed tags, so any
re-hardcoded form will include the ``v``.

The patterns are quoted-quote-aware: a single backreference matches
the opening quote to the closing quote, so ``'1.0.0"`` (mismatched
quotes) doesn't false-positive.

Covers R5 in
``docs/brainstorms/2026-06-25-version-source-of-truth-requirements.md``.
"""

import re
from pathlib import Path
from typing import List, Tuple

from django.test import SimpleTestCase

# A quoted string carrying a three-segment semver (optionally ``v``-prefixed),
# possibly wrapped in chart-style prefix garbage (``dev2-v1.1.0``). The quote
# style is back-referenced so a mismatched-quote artifact like ``"x'`` cannot
# trigger a spurious match.
_QUOTED_VERSION_BODY = (
    r"""(?P<q>['"])[^'"\n]*?\bv?\d+\.\d+\.\d+\b[^'"\n]*?(?P=q)"""
)

ASSIGNMENT_PATTERN = re.compile(
    r"\b(__version__|APP_VERSION)\s*=\s*"
    + r"""['"][^'"\n]*?\bv?\d+\.\d+\.\d+\b[^'"\n]*?['"]"""
)
QUOTED_SEMVER_PATTERN = re.compile(_QUOTED_VERSION_BODY)
VERSION_KEYWORD_PATTERN = re.compile(r"version", re.IGNORECASE)

APP_ROOT = Path(__file__).resolve().parent.parent.parent
EXCLUDED_DIR_NAMES = {"tests", "migrations", "__pycache__"}


def _is_excluded(path: Path) -> bool:
    """Return True when the file lives under an excluded directory."""
    return any(part in EXCLUDED_DIR_NAMES for part in path.relative_to(APP_ROOT).parts)


def _scan_file(path: Path) -> List[Tuple[int, str]]:
    """Scan a single ``.py`` file for version-literal hits.

    Args:
        path: The file to scan.

    Returns:
        A list of ``(lineno, line)`` tuples — one per offending line.
        Empty when the file is clean.
    """
    hits: List[Tuple[int, str]] = []
    text = path.read_text(encoding="utf-8")
    for lineno, line in enumerate(text.splitlines(), start=1):
        if ASSIGNMENT_PATTERN.search(line):
            hits.append((lineno, line))
            continue
        if QUOTED_SEMVER_PATTERN.search(line) and VERSION_KEYWORD_PATTERN.search(line):
            hits.append((lineno, line))
    return hits


class NoVersionLiteralsTests(SimpleTestCase):
    """Production source must not carry hardcoded version literals."""

    def test_no_hardcoded_version_literals_in_production_source(self) -> None:
        offenders: List[str] = []
        for path in APP_ROOT.rglob("*.py"):
            if _is_excluded(path):
                continue
            for lineno, line in _scan_file(path):
                rel = path.relative_to(APP_ROOT)
                offenders.append(f"  {rel}:{lineno}: {line.strip()}")

        self.assertFalse(
            offenders,
            "Found hardcoded version literals in production source. "
            "Route all version display through settings.APP_VERSION "
            "(which reads the APP_VERSION env var the Helm chart sets "
            "from .Values.image.tag):\n" + "\n".join(offenders),
        )


class GuardPatternsTests(SimpleTestCase):
    """Unit tests for the guard's regex patterns.

    The live scan above proves the guard reports zero offenders today.
    These unit tests prove the guard would FIRE if a regression were
    introduced — closing the gap where a future edit could silently
    weaken a pattern without breaking the suite.
    """

    @staticmethod
    def _flags(line: str) -> bool:
        return bool(
            ASSIGNMENT_PATTERN.search(line)
            or (
                QUOTED_SEMVER_PATTERN.search(line)
                and VERSION_KEYWORD_PATTERN.search(line)
            )
        )

    # --- positives: lines the guard MUST flag ---

    def test_flags_dunder_version_assignment(self) -> None:
        self.assertTrue(self._flags('__version__ = "1.2.3"'))

    def test_flags_app_version_assignment(self) -> None:
        self.assertTrue(self._flags('APP_VERSION = "1.2.3"'))

    def test_flags_app_version_assignment_with_v_prefix(self) -> None:
        self.assertTrue(self._flags('APP_VERSION = "v1.0.0"'))

    def test_flags_app_version_assignment_with_chart_style_tag(self) -> None:
        self.assertTrue(self._flags('APP_VERSION = "dev2-v1.1.0"'))

    def test_flags_quoted_semver_dict_value(self) -> None:
        self.assertTrue(self._flags('    "version": "1.0.0",'))

    def test_flags_quoted_v_prefixed_dict_value(self) -> None:
        self.assertTrue(self._flags("    'version': 'v1.0.0',"))

    # --- negatives: lines the guard MUST NOT flag ---

    def test_does_not_flag_django_docstring_mention(self) -> None:
        self.assertFalse(
            self._flags(
                "Generated by 'django-admin startproject' using Django 3.2.9."
            )
        )

    def test_does_not_flag_ip_literal(self) -> None:
        self.assertFalse(
            self._flags("        'HOST': os.getenv('DB_HOST', '127.0.0.1'),")
        )

    def test_does_not_flag_dependency_version_comment(self) -> None:
        self.assertFalse(
            self._flags(
                "# vs the runtime 1.9.0+), which surfaces an "
                "InconsistentVersionWarning"
            )
        )

    def test_does_not_flag_python_version_comment(self) -> None:
        self.assertFalse(
            self._flags("# under Python 3.13 + numba 0.65.1")
        )

    def test_does_not_flag_mismatched_quote_artifact(self) -> None:
        """Backreferenced quote pair rejects mismatched-quote pseudo-matches."""
        self.assertFalse(self._flags(""""version" is "1.0.0' """))
