"""Regression guard: no hardcoded version literals in production source.

Without this guard, a future change can reintroduce the exact bug R5
exists to prevent — e.g. ``__version__ = "1.2.3"`` in a new module, or
``APP_VERSION = "1.2.3"`` re-hardcoded — and the displayed footer
silently drifts from the deployed image tag again.

The scan excludes tests/, migrations/, and __pycache__/ — version
references in auto-generated migrations are legitimate, and test
fixtures may need version-shaped strings for their own purposes.

Pattern (b) (three-segment semver) only fires on lines that contain a
**quoted** semver AND the case-insensitive keyword ``version``. The
plan prescribed a bare-semver-plus-keyword rule, but a dry run against
the codebase surfaced a false positive — the unquoted ``1.9.0`` in
``# InconsistentVersionWarning`` comments contains ``Version`` as a
substring of the warning class name, so the keyword filter alone is
insufficient. Requiring the semver to be quoted preserves the plan's
intent — catch ``APP_VERSION = "x.y.z"`` and ``"version": "x.y.z"``
shapes while passing over the ``Django 3.2.9`` docstring in
settings.py, the ``'127.0.0.1'`` IP literal in the same file, and the
sklearn / numba / umap-learn dependency version comments in
twins_search_service.py.

Covers R5 in
``docs/brainstorms/2026-06-25-version-source-of-truth-requirements.md``.
"""

import re
from pathlib import Path
from typing import List, Tuple

from django.test import SimpleTestCase

ASSIGNMENT_PATTERN = re.compile(r"__version__\s*=")
QUOTED_SEMVER_PATTERN = re.compile(r"""['"]\d+\.\d+\.\d+['"]""")
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
