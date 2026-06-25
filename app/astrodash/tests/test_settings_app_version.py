"""Tests for the ``APP_VERSION`` resolution in Django settings.

``settings.APP_VERSION`` is sourced from the ``APP_VERSION`` environment
variable. Under Kubernetes the Helm chart sets it from the deployed
image tag (e.g. ``dev2-v1.1.0``). In local development the variable is
unset and the resolver falls back to the literal string ``local`` — a
non-semver-shaped placeholder picked so a deploy that accidentally
ships without the env var cannot impersonate a real release in the
footer.

Covers R1 in
``docs/brainstorms/2026-06-25-version-source-of-truth-requirements.md``.
"""

import os
from unittest import mock

from django.conf import settings
from django.test import SimpleTestCase

from astrodash_project.settings import _resolve_app_version


class ResolveAppVersionTests(SimpleTestCase):
    """Unit tests for the ``_resolve_app_version`` helper in isolation."""

    @mock.patch.dict(os.environ, {"APP_VERSION": "dev2-v1.1.0"}, clear=False)
    def test_returns_env_var_value_when_set(self) -> None:
        """A set, non-empty env var is returned verbatim."""
        self.assertEqual(_resolve_app_version(), "dev2-v1.1.0")

    @mock.patch.dict(os.environ, {"APP_VERSION": "v1.0.0"}, clear=False)
    def test_returns_env_var_value_with_v_prefix(self) -> None:
        """The chart's ``v``-prefixed tag is passed through unchanged."""
        self.assertEqual(_resolve_app_version(), "v1.0.0")

    def test_falls_back_to_local_when_unset(self) -> None:
        """An unset env var resolves to the ``local`` placeholder."""
        env = os.environ.copy()
        env.pop("APP_VERSION", None)
        with mock.patch.dict(os.environ, env, clear=True):
            self.assertEqual(_resolve_app_version(), "local")

    @mock.patch.dict(os.environ, {"APP_VERSION": ""}, clear=False)
    def test_falls_back_to_local_when_empty_string(self) -> None:
        """An empty env var (``APP_VERSION=``) is treated as unset.

        The ``or`` form in the resolver — rather than ``os.environ.get``'s
        second positional default — is what makes this happen.
        """
        self.assertEqual(_resolve_app_version(), "local")


class SettingsAppVersionTests(SimpleTestCase):
    """Integration: ``settings.APP_VERSION`` is a non-empty string at import time."""

    def test_app_version_is_non_empty_string(self) -> None:
        self.assertIsInstance(settings.APP_VERSION, str)
        self.assertTrue(settings.APP_VERSION)

    def test_app_version_has_no_v_prefix_injected_by_settings(self) -> None:
        """Settings does not prepend ``v`` — that's the chart's job (R2).

        Under the test environment the env var is unset, so the resolver
        returns ``local`` — not ``vlocal`` or ``vNone``.
        """
        env_value = os.environ.get("APP_VERSION")
        if env_value:
            self.assertEqual(settings.APP_VERSION, env_value)
        else:
            self.assertEqual(settings.APP_VERSION, "local")
