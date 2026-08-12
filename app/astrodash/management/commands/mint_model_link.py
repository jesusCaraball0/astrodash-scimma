"""Mint a model-scoped entry link for a gated model.

This command is the *only* way to produce an entry link: no URL route mints
one, so a link can only come from an operator with shell access to a running
deployment. The operator hands the printed link, plus the shared credential
(which this command deliberately never prints), to whoever distributes them.
"""

from typing import Any

from django.core.management.base import BaseCommand, CommandError
from django.urls import reverse

from astrodash.core.gate_config import LINK_BASE_URL_ENV_VAR, link_base_url
from astrodash.core.model_access import GateNotConfigured, mint_entry_link
from astrodash.infrastructure.ml.model_registry import get_definition


class Command(BaseCommand):
    """Print an entry link for one gated model."""

    help = (
        "Mint a model-scoped entry link for a gated model. The link expires, and "
        "redeeming it still requires the shared access code, which this command "
        "does not print."
    )

    def add_arguments(self, parser: Any) -> None:
        """Declare the command's arguments.

        Args:
            parser: The argument parser supplied by Django.
        """
        parser.add_argument(
            "model_id",
            help="The id of the gated model the link should grant access to.",
        )
        parser.add_argument(
            "--ttl-seconds",
            type=int,
            default=None,
            help=(
                "Override the configured expiry window, in seconds. The deadline "
                "is stamped into the link when it is minted."
            ),
        )

    def handle(self, *args: Any, **options: Any) -> None:
        """Mint the link and print it.

        Args:
            *args: Unused positional arguments.
            **options: Parsed command options.

        Raises:
            CommandError: If the model is unknown or not gated, if the link host
                is unconfigured, or if the gate's own configuration is missing.
        """
        model_id = options["model_id"]
        ttl_seconds = options["ttl_seconds"]

        definition = get_definition(model_id)
        if definition is None:
            raise CommandError(f"No such model: '{model_id}'.")
        if not definition.requires_credential:
            raise CommandError(
                f"Model '{model_id}' does not require a credential, so it needs "
                "no entry link. It is reachable through the normal flow."
            )

        base_url = link_base_url()
        if base_url is None:
            raise CommandError(
                f"{LINK_BASE_URL_ENV_VAR} is not configured. The application sits "
                "behind a proxy, so the link host is configured rather than "
                "inferred."
            )

        if ttl_seconds is not None and ttl_seconds <= 0:
            raise CommandError("--ttl-seconds must be a positive number of seconds.")

        try:
            token = mint_entry_link(model_id, ttl_seconds=ttl_seconds)
        except GateNotConfigured as exc:
            raise CommandError(str(exc)) from exc

        path = reverse("astrodash:model_gate", args=[token])
        self.stdout.write(f"{base_url}{path}")
