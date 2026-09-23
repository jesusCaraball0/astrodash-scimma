"""The REST API keeps its JSON error contract when settings fail to load.

Every view in ``views.py`` resolves its service locators before the
``try``/``except`` that builds the JSON body, so a malformed ``ASTRODASH_*``
value raised out of the view and Django rendered an HTML 500 page -- on an
endpoint whose every other failure answers ``{"detail": ...}``.

That path only became reachable when the ``ASTRODASH_*`` variables started
binding (see ``test_settings_env_binding.py``); a bad value was previously
discarded in silence. ``apps.AstroDashConfig.ready`` now builds ``Settings``
once at startup so a bad value fails the rollout, and
``middleware.ConfigurationErrorMiddleware`` catches the case that startup
cannot: ``get_settings()`` is uncached, so a value can go bad under an
already-running process.
"""

import json
from unittest import mock

from django.http import JsonResponse
from django.test import SimpleTestCase, TestCase
from django.urls import reverse
from pydantic import ValidationError

from astrodash.config.settings import Settings, get_settings
from astrodash.middleware import ConfigurationErrorMiddleware, _offending_fields


def _settings_error() -> ValidationError:
    """A real ValidationError from a rejected ASTRODASH_* value."""
    with mock.patch.dict("os.environ", {"ASTRODASH_NW": "not-a-number"}):
        try:
            Settings()
        except ValidationError as exc:
            return exc
    raise AssertionError("ASTRODASH_NW=not-a-number did not raise")


class StartupValidationTests(SimpleTestCase):
    """A bad value fails the init container rather than the first request."""

    def test_bad_value_raises_when_settings_are_built(self):
        with self.assertRaises(ValidationError):
            with mock.patch.dict("os.environ", {"ASTRODASH_NW": "not-a-number"}):
                Settings()

    def test_ready_builds_settings(self):
        """Regression guard: ready() must actually touch Settings."""
        from astrodash.apps import AstroDashConfig

        with mock.patch(
            "astrodash.config.settings.get_settings", wraps=get_settings
        ) as spy:
            config = AstroDashConfig.create("astrodash")
            config.ready()
        self.assertTrue(spy.called, "ready() no longer builds Settings at startup")


class ConfigurationErrorMiddlewareTests(SimpleTestCase):
    """The middleware answers for API views only, and leaks no values."""

    def _apply(self, module, exception):
        middleware = ConfigurationErrorMiddleware(lambda request: None)
        request = mock.Mock()
        request.path = "/astrodash/api/v1/process"
        request.resolver_match = mock.Mock()
        request.resolver_match.func.__module__ = module
        return middleware.process_exception(request, exception)

    def test_api_view_config_error_returns_json_envelope(self):
        response = self._apply("astrodash.views", _settings_error())
        self.assertIsInstance(response, JsonResponse)
        self.assertEqual(response.status_code, 500)
        self.assertEqual(
            json.loads(response.content), {"detail": "Server configuration error"}
        )

    def test_ui_view_is_left_to_django(self):
        self.assertIsNone(self._apply("astrodash.ui_views", _settings_error()))

    def test_unrelated_exception_is_left_alone(self):
        self.assertIsNone(self._apply("astrodash.views", ValueError("unrelated")))

    def test_response_body_carries_no_rejected_value(self):
        """ValidationError carries input_value; ASTRODASH_DATABASE_URL is a secret."""
        response = self._apply("astrodash.views", _settings_error())
        self.assertNotIn(b"not-a-number", response.content)

    def test_log_names_fields_without_values(self):
        fields = _offending_fields(_settings_error())
        self.assertIn("nw", fields)
        self.assertNotIn("not-a-number", fields)


class ProcessEndpointContractTests(TestCase):
    """End to end: the endpoint answers JSON, not an HTML error page."""

    def test_config_failure_returns_json_not_html(self):
        url = reverse("astrodash_api:process_spectrum")
        # API writes are gated off by default; turn them on so the view body
        # runs, matching test_api_model_type.py.
        with mock.patch("astrodash.views.API_WRITES_ENABLED", True), mock.patch(
            "astrodash.views.get_classification_service",
            side_effect=_settings_error(),
        ):
            response = self.client.post(url, data={"params": '{"modelType": "dash"}'})
        self.assertEqual(response.status_code, 500)
        self.assertEqual(response["Content-Type"], "application/json")
        self.assertEqual(
            json.loads(response.content), {"detail": "Server configuration error"}
        )
