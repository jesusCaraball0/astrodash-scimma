"""Regression guard: ``docker-compose.dev.yaml`` carries the APP_VERSION line.

Without this guard, a future compose edit can silently drop
``APP_VERSION=${APP_VERSION:-local}`` from the app service's ``environment:``
block. When that happens, ``astrodashctl full_dev up`` still exports the
git-describe value on the host, but the value never reaches the container
and the footer reverts to the literal ``local`` — the same footer we saw
before the local-dev version work landed.

The guard scans the compose file with a small regex rather than parsing
YAML. Pattern-matching mirrors the shape of
``test_no_version_literals.py`` from the parent brainstorm and keeps the
test resilient to whitespace or quote-style reformatting.

Covers R4 in
``docs/brainstorms/2026-07-01-local-dev-app-version-requirements.md``.
"""

import re
import unittest
from pathlib import Path
from typing import Final

from django.test import SimpleTestCase


# The literal token that must appear in ``docker/docker-compose.dev.yaml``:
#
#     APP_VERSION=${APP_VERSION:-local}
#
# The compose file quotes its ``environment:`` entries as strings, so the
# form in the file is ``- "APP_VERSION=${APP_VERSION:-local}"`` (or the
# single-quoted equivalent). The regex is written against the token itself
# and does not care which quote style wraps it.
APP_VERSION_LINE_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"APP_VERSION=\$\{APP_VERSION:-local\}"
)

# ``Path(__file__).resolve().parents[3]`` steps: tests/ -> astrodash/ -> app/ ->
# repo root. Four hops from this file. This assumes the tests run from a
# checkout where ``docker/docker-compose.dev.yaml`` sits at the repo root — true
# for host-side runs (``pytest`` at repo root, CI). Inside the dev container
# only ``app/`` is bind-mounted, so ``docker/`` isn't reachable — the live scan
# skips itself in that context. The pattern tests below still fire either way.
REPO_ROOT: Final[Path] = Path(__file__).resolve().parents[3]
COMPOSE_FILE: Final[Path] = REPO_ROOT / "docker" / "docker-compose.dev.yaml"


class ComposeAppVersionLineTests(SimpleTestCase):
    """The dev compose file must carry the ``APP_VERSION`` env-var entry."""

    @unittest.skipUnless(
        COMPOSE_FILE.exists(),
        f"{COMPOSE_FILE} not reachable — likely running from inside the dev "
        "container, where only app/ is bind-mounted. Run the suite from the "
        "repo root on the host to exercise this scan.",
    )
    def test_live_compose_file_contains_app_version_entry(self) -> None:
        """The live ``docker/docker-compose.dev.yaml`` file matches the guard.

        The compose file's app service must include
        ``APP_VERSION=${APP_VERSION:-local}`` in its ``environment:`` block so
        the value exported by ``run/astrodashctl`` reaches the container.
        """
        text = COMPOSE_FILE.read_text(encoding="utf-8")
        self.assertTrue(
            APP_VERSION_LINE_PATTERN.search(text),
            f"Expected {COMPOSE_FILE.relative_to(REPO_ROOT)} to contain "
            f"``APP_VERSION=${{APP_VERSION:-local}}`` in the app service's "
            f"``environment:`` block. Without it, ``astrodashctl full_dev up`` "
            f"exports the git-describe value on the host but the value never "
            f"reaches the container, and the footer reverts to ``local``.",
        )


class GuardPatternTests(SimpleTestCase):
    """Unit tests for the guard's regex.

    The live scan above proves the guard passes today. These tests prove
    the guard would FIRE if a regression were introduced — closing the gap
    where a future edit could silently weaken the pattern without breaking
    the suite.
    """

    def test_matches_double_quoted_compose_entry(self) -> None:
        """The double-quoted YAML list form matches."""
        line = '      - "APP_VERSION=${APP_VERSION:-local}"'
        self.assertIsNotNone(APP_VERSION_LINE_PATTERN.search(line))

    def test_matches_single_quoted_compose_entry(self) -> None:
        """The single-quoted YAML list form also matches."""
        line = "      - 'APP_VERSION=${APP_VERSION:-local}'"
        self.assertIsNotNone(APP_VERSION_LINE_PATTERN.search(line))

    def test_does_not_match_when_line_is_missing(self) -> None:
        """A compose fragment with the APP_VERSION entry removed fails the guard."""
        yaml_fragment = (
            "    environment:\n"
            '      - "DEV_MODE=1"\n'
            '      - "ASTRO_DASH_CORS_ALLOWED_ORIGINS=*"\n'
            '      - "ASTRODASH_LOG_LEVEL=DEBUG"\n'
        )
        self.assertIsNone(APP_VERSION_LINE_PATTERN.search(yaml_fragment))

    def test_does_not_match_bare_app_version_assignment(self) -> None:
        """``APP_VERSION=`` without the ``${APP_VERSION:-local}`` fallback fails."""
        line = '      - "APP_VERSION="'
        self.assertIsNone(APP_VERSION_LINE_PATTERN.search(line))
