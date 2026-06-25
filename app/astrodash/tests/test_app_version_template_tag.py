"""Tests for the ``app_version`` template tag.

Post-U1, ``{% app_version %}`` is a zero-argument tag that returns
``settings.APP_VERSION`` verbatim. The historical ``v`` prefix that
the tag used to prepend is gone — the chart's image tag may already
carry a ``v`` (``v1.0.0``), and the footer renders that value
unmodified so the GitHub release link target resolves correctly.

Covers R2 in
``docs/brainstorms/2026-06-25-version-source-of-truth-requirements.md``.
"""

from django.template import Context, Template
from django.test import SimpleTestCase, override_settings


class AppVersionTemplateTagTests(SimpleTestCase):
    """Render-time behavior of the ``app_version`` template tag."""

    @staticmethod
    def _render() -> str:
        """Render ``{% app_version %}`` against an empty context.

        Returns:
            The rendered output of the tag.
        """
        template = Template("{% load astrodash_tags %}{% app_version %}")
        return template.render(Context({}))

    @override_settings(APP_VERSION="dev2-v1.1.0")
    def test_renders_settings_app_version_verbatim(self) -> None:
        """The tag returns settings.APP_VERSION exactly — no prefix added."""
        self.assertEqual(self._render(), "dev2-v1.1.0")

    @override_settings(APP_VERSION="v1.0.0")
    def test_does_not_double_prepend_v(self) -> None:
        """A chart tag already starting with ``v`` is not double-prepended."""
        self.assertEqual(self._render(), "v1.0.0")

    @override_settings(APP_VERSION="local")
    def test_renders_local_placeholder_verbatim(self) -> None:
        """The local-dev placeholder renders as ``local`` (not ``vlocal``)."""
        self.assertEqual(self._render(), "local")
