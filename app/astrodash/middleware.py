"""Django middleware for the REST API's error contract.

``core/middleware.py`` is Starlette/FastAPI code left from the pre-Django
layout and has no caller; this module is the Django one.
"""

from django.http import JsonResponse
from pydantic import ValidationError
from pydantic_settings.sources import SettingsError

from astrodash.config.logging import get_logger

logger = get_logger(__name__)

# The REST views whose failures are contracted to be JSON. The UI views in
# ui_views.py render HTML and keep Django's normal error handling.
API_VIEW_MODULE = "astrodash.views"


class ConfigurationErrorMiddleware:
    """Return the API's JSON envelope when settings fail to load.

    Every view in ``views.py`` resolves its service locators *before* the
    ``try``/``except`` that builds the JSON error body -- ``views.py:230`` is
    one of about fifteen. A malformed ``ASTRODASH_*`` value raises there, so
    the endpoint answered with a Django HTML 500 page while every other
    failure on the same endpoint returns ``{"detail": ...}``.

    That was unreachable until the settings class started reading the
    environment at all: a bad value used to be discarded in silence. The
    startup check in ``apps.AstroDashConfig.ready`` is the primary guard and
    fails the init container. This is the second layer, because
    ``get_settings()`` is uncached and re-reads the environment on every call,
    so a value can go bad under an already-running process.

    The response body is deliberately generic. A pydantic ``ValidationError``
    carries the rejected ``input_value``, and for ``ASTRODASH_DATABASE_URL``
    that is a credential-bearing URL -- it must not reach an HTTP response.
    The log line names the offending fields without their values.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        return self.get_response(request)

    def process_exception(self, request, exception):
        if not isinstance(exception, (ValidationError, SettingsError)):
            return None

        match = getattr(request, "resolver_match", None)
        if match is None or getattr(match.func, "__module__", "") != API_VIEW_MODULE:
            return None

        logger.error(
            "Configuration error serving %s: %s (fields: %s)",
            request.path,
            type(exception).__name__,
            _offending_fields(exception),
        )
        return JsonResponse({"detail": "Server configuration error"}, status=500)


def _offending_fields(exception) -> str:
    """Name the fields a ValidationError rejected, never their values."""
    errors = getattr(exception, "errors", None)
    if not callable(errors):
        return "unknown"
    try:
        names = sorted(
            {".".join(str(part) for part in err.get("loc", ())) for err in errors()}
        )
    except Exception:  # noqa: BLE001 - never let logging mask the original error
        return "unknown"
    return ", ".join(name for name in names if name) or "unknown"
