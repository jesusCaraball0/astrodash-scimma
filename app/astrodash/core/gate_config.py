"""Deployment configuration for the gated-model access gate.

A model definition can declare that running it requires a shared credential
(see :mod:`astrodash.infrastructure.ml.model_registry`). Serving such a model
needs three deployment-supplied values: the shared credential itself, the
entry-link expiry window, and the key used to sign entry links. This module is
the single place those values are read and normalized, so the startup check and
the gate itself cannot drift apart on names or defaults.

The values are read here -- in the web/core layer -- rather than in the model
registry: nothing under ``astrodash.infrastructure`` imports Django or reads the
environment, and the registry validator takes this configuration as an argument
instead.

Normalization is deliberately strict, because R34 requires a misconfigured
deployment to fail closed rather than serve a gated model without a prompt:

* an unset, empty, or whitespace-only value is unconfigured;
* an expiry window that is not a positive integer is unconfigured;
* a signing key left at the committed ``django-insecure-`` default -- the value
  ``astrodash_project.settings`` falls back to when ``SECRET_KEY`` is unset --
  is unconfigured, since a key published in the repository signs nothing.
"""

import os
from typing import Dict, Optional

from django.conf import settings

# Environment variables and setting names carrying the gate's configuration.
# These names appear verbatim in the startup failure message, so an operator
# reads the missing configuration straight off the pod log.
CREDENTIAL_ENV_VAR = "ASTRODASH_MODEL_GATE_CREDENTIAL"
LINK_TTL_ENV_VAR = "ASTRODASH_MODEL_GATE_LINK_TTL_SECONDS"
SIGNING_KEY_NAME = "SECRET_KEY"

# Base URL entry links are minted against. It is deliberately *not* part of
# :func:`gate_configuration`, and so not part of the startup fail-closed check:
# a deployment with no link host still serves an already-minted link correctly,
# and only the operator minting a new one needs it. The app sits behind a proxy,
# so the host is configured rather than inferred from a request.
LINK_BASE_URL_ENV_VAR = "ASTRODASH_MODEL_GATE_LINK_BASE_URL"

# Prefix of the placeholder signing key committed to the repository. Django
# stamps generated placeholder keys with it, and a key carrying it is public.
INSECURE_SIGNING_KEY_PREFIX = "django-insecure-"


def _configured(value: Optional[str]) -> Optional[str]:
    """Normalize a raw configuration value, treating blanks as unconfigured.

    Args:
        value: The raw value as read from the environment or settings.

    Returns:
        The stripped value, or ``None`` when it is unset, empty, or
        whitespace-only.
    """
    if value is None:
        return None
    stripped = str(value).strip()
    return stripped or None


def _credential() -> Optional[str]:
    """Return the configured shared credential, or ``None`` if unconfigured."""
    return _configured(os.environ.get(CREDENTIAL_ENV_VAR))


def _link_ttl_seconds() -> Optional[str]:
    """Return the configured entry-link expiry window in seconds.

    Returns:
        The window as a string, or ``None`` when it is unset, blank, or not a
        positive integer.
    """
    raw = _configured(os.environ.get(LINK_TTL_ENV_VAR))
    if raw is None:
        return None
    try:
        seconds = int(raw)
    except ValueError:
        return None
    return raw if seconds > 0 else None


def _signing_key() -> Optional[str]:
    """Return the configured signing key, or ``None`` if unconfigured.

    Returns:
        The key from ``settings.SECRET_KEY``, or ``None`` when it is blank or
        still the committed ``django-insecure-`` placeholder.
    """
    key = _configured(getattr(settings, SIGNING_KEY_NAME, None))
    if key is None or key.startswith(INSECURE_SIGNING_KEY_PREFIX):
        return None
    return key


def link_base_url() -> Optional[str]:
    """Return the base URL entry links are minted against.

    Returns:
        The configured base URL with any trailing slash removed, or ``None``
        when it is unset, empty, or whitespace-only. Only the mint command
        needs it, so an unconfigured value is not a startup failure.
    """
    base = _configured(os.environ.get(LINK_BASE_URL_ENV_VAR))
    return base.rstrip("/") if base else None


def gate_configuration() -> Dict[str, Optional[str]]:
    """Read the gate's deployment configuration, normalized.

    Returns:
        A mapping of configuration name to its normalized value, with ``None``
        for every value that is unset, blank, or left at a committed default.
        The keys are the names an operator sets, so a validator can name the
        missing configuration back to them.
    """
    return {
        CREDENTIAL_ENV_VAR: _credential(),
        LINK_TTL_ENV_VAR: _link_ttl_seconds(),
        SIGNING_KEY_NAME: _signing_key(),
    }
