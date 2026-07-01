"""Tests for the ``/healthz`` payload's version field.

``get_health_status()`` in ``app/astrodash/core/monitoring.py`` is the
dormant /healthz response builder; it is not currently wired to any
URL pattern. The contract this test enforces — that its ``version``
key reflects ``settings.APP_VERSION`` — applies anyway, so the file
is ready when a view eventually routes to it without a silent drift
back to a hardcoded literal.

Covers R4 / AE4 in
``docs/brainstorms/2026-06-25-version-source-of-truth-requirements.md``.
"""

from django.test import SimpleTestCase, override_settings

from astrodash.core.monitoring import get_health_status


class HealthStatusVersionTests(SimpleTestCase):
    """``get_health_status()['version']`` tracks ``settings.APP_VERSION``."""

    @override_settings(APP_VERSION="dev2-v1.1.0")
    def test_version_field_reflects_app_version(self) -> None:
        result = get_health_status()
        self.assertEqual(result["version"], "dev2-v1.1.0")

    @override_settings(APP_VERSION="v1.0.0")
    def test_version_field_passes_through_v_prefixed_tag(self) -> None:
        result = get_health_status()
        self.assertEqual(result["version"], "v1.0.0")

    @override_settings(APP_VERSION="local")
    def test_version_field_carries_local_placeholder(self) -> None:
        result = get_health_status()
        self.assertEqual(result["version"], "local")

    @override_settings(APP_VERSION="anything")
    def test_no_hardcoded_version_returned(self) -> None:
        """A regression that replaced ``settings.APP_VERSION`` with a literal
        would surface here even when ``override_settings`` is in effect."""
        result = get_health_status()
        self.assertNotEqual(result["version"], "1.0.0")
        self.assertEqual(result["version"], "anything")
