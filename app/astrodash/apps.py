from django.apps import AppConfig
from django.conf import settings


class AstroDashConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "astrodash"
    verbose_name = "AstroDash Integration"

    def ready(self) -> None:
        """Announce the active ``APP_VERSION`` at app startup.

        One INFO line at gunicorn boot so operators can confirm what's
        running from pod logs without exec'ing into the container.
        Django may call ``ready()`` more than once in some test setups;
        a duplicated log line is harmless.
        """
        from astrodash.config.logging import get_logger

        get_logger(__name__).info(
            "AstroDash starting with APP_VERSION=%s", settings.APP_VERSION
        )
