from django.apps import AppConfig
from django.conf import settings


class AstroDashConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "astrodash"
    verbose_name = "AstroDash Integration"

    def ready(self) -> None:
        """Announce the active ``APP_VERSION`` and fail closed on a misconfigured gate.

        One INFO line at gunicorn boot so operators can confirm what's
        running from pod logs without exec'ing into the container.
        Django may call ``ready()`` more than once in some test setups;
        a duplicated log line is harmless.

        The gate-configuration check runs here rather than at registry import
        because ``ready()`` runs for the server *and* every management command:
        a deployment whose registry contains a gated model but lacks the gate's
        configuration fails in the init container, rather than starting and
        serving that model without a credential prompt.

        Raises:
            ValueError: If a model in the registry requires a credential while
                any part of the gate configuration is unset, blank, or left at
                a committed default.
        """
        from astrodash.config.logging import get_logger
        from astrodash.core.gate_config import gate_configuration
        from astrodash.infrastructure.ml import model_registry

        get_logger(__name__).info(
            "AstroDash starting with APP_VERSION=%s", settings.APP_VERSION
        )

        model_registry.validate_gate_configuration(
            model_registry.MODELS, gate_configuration()
        )
