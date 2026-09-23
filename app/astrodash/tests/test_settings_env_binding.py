"""Regression guard: every ``ASTRODASH_*`` variable actually binds.

Every field in ``astrodash/config/settings.py`` was declared as
``Field(default, env="ASTRODASH_X")``. That ``env=`` keyword is a pydantic
v1 idiom. This project has only ever run pydantic v2 (``pydantic==2.5.0``
arrived in the same commit as the idiom), and v2's ``Field()`` has no
``env`` parameter -- it sweeps unknown keywords into ``json_schema_extra``
and moves on. ``pydantic_settings`` therefore never saw those names and
built its lookup key from ``env_prefix + field_name`` instead, which with
no prefix and ``case_sensitive = True`` meant the bare lowercase field
name. So ``ASTRODASH_LOG_LEVEL=DEBUG`` in docker-compose.dev.yaml set
nothing: ``settings.log_level`` stayed at its ``INFO`` default.

All 76 variables were inert, which is why nothing looked broken: a
setting nobody overrides and a setting whose override is discarded are
indistinguishable until someone tries to override it. No user-visible
behaviour changed when this was fixed -- every variable an operator
actually sets already held its default value. The defect was that the
configuration mechanism silently discarded operator intent, which would
have produced a genuine outage the first time someone relied on it.

pydantic *does* emit ``PydanticDeprecatedSince20`` once per field for the
stray keyword, but ``DeprecationWarning`` is hidden by default outside
``__main__``, so 76 warnings a run went unseen. These tests assert the
binding itself rather than trusting a warning nobody sees.

The Kubernetes guard is not hypothetical. Services in the ``astrodash``
namespace are named ``astrodash-web``, ``astrodash-redis`` and
``astrodash-postgresql``, so Kubernetes injects 21 service-discovery
variables that already begin with ``ASTRODASH_`` into every pod
(``ASTRODASH_REDIS_SERVICE_HOST``, ``ASTRODASH_WEB_PORT_8000_TCP``, ...).
None collide with a field today. A field named ``web_port`` or
``redis_service_host`` would be silently fed by Kubernetes rather than by
the configMap, so the collision test below refuses those prefixes.
"""

import os
from unittest import mock

from django.test import SimpleTestCase

from astrodash.config.settings import Settings, get_settings

# The five fields whose documented variable is not ``ASTRODASH_`` plus the
# uppercased field name. Pinned so a rename cannot quietly repoint a
# variable an operator already sets.
EXPLICIT_ALIASES = {
    "db_url": "ASTRODASH_DATABASE_URL",
    "oned_cnn_z_model_path": "ASTRODASH_1DCNN_Z_MODEL_PATH",
    "oned_cnn_z_class_mapping_path": "ASTRODASH_1DCNN_Z_CLASS_MAPPING_PATH",
    "oned_cnn_noz_model_path": "ASTRODASH_1DCNN_NOZ_MODEL_PATH",
    "oned_cnn_noz_class_mapping_path": "ASTRODASH_1DCNN_NOZ_CLASS_MAPPING_PATH",
}

# Prefixes Kubernetes claims for service discovery in the astrodash
# namespace, with the ``ASTRODASH_`` prefix already stripped.
KUBERNETES_SERVICE_PREFIXES = ("web_", "redis_", "postgresql_")


def resolved_env_name(field_name, field):
    """Return the environment variable pydantic-settings will look up."""
    alias = field.validation_alias
    if alias is None:
        prefix = Settings.model_config.get("env_prefix", "")
        return f"{prefix}{field_name}".upper()
    choices = getattr(alias, "choices", None)
    return (choices[0] if choices else alias).upper()


class EnvPrefixConfigurationTests(SimpleTestCase):
    """The settings class is wired so the documented names can bind at all."""

    def test_env_prefix_is_configured(self):
        self.assertEqual(Settings.model_config.get("env_prefix"), "ASTRODASH_")

    def test_lookup_is_case_insensitive(self):
        # ASTRODASH_LOG_LEVEL must reach the lowercase field ``log_level``.
        self.assertFalse(Settings.model_config.get("case_sensitive", False))

    def test_no_field_carries_the_dead_env_keyword(self):
        """``Field(env=...)`` is silently ignored by pydantic v2 -- ban it."""
        offenders = sorted(
            name
            for name, field in Settings.model_fields.items()
            if isinstance(field.json_schema_extra, dict)
            and "env" in field.json_schema_extra
        )
        self.assertEqual(
            offenders,
            [],
            "Field(env=...) does nothing in pydantic v2; the variable will "
            "never bind. Use the ASTRODASH_ prefix, or validation_alias for "
            f"a name the prefix cannot produce. Offending fields: {offenders}",
        )


class ResolvedNameTests(SimpleTestCase):
    """Every field resolves to the ASTRODASH_* name operators are told to use."""

    def test_every_field_resolves_to_an_astrodash_name(self):
        for name, field in Settings.model_fields.items():
            with self.subTest(field=name):
                self.assertTrue(
                    resolved_env_name(name, field).startswith("ASTRODASH_"),
                    f"{name} does not resolve to an ASTRODASH_* variable",
                )

    def test_aliased_fields_keep_their_documented_names(self):
        for name, expected in EXPLICIT_ALIASES.items():
            with self.subTest(field=name):
                field = Settings.model_fields[name]
                self.assertEqual(resolved_env_name(name, field), expected)

    def test_no_field_collides_with_kubernetes_service_discovery(self):
        """A field named ``web_port`` would be fed by Kubernetes, not config."""
        offenders = sorted(
            name
            for name in Settings.model_fields
            if name.lower().startswith(KUBERNETES_SERVICE_PREFIXES)
            and name not in EXPLICIT_ALIASES
        )
        self.assertEqual(
            offenders,
            [],
            "Kubernetes injects ASTRODASH_<SERVICE>_* into every pod for the "
            "astrodash-web / astrodash-redis / astrodash-postgresql services. "
            f"These field names would be overridden by it: {offenders}",
        )


class EveryFieldBindsTests(SimpleTestCase):
    """Drive the assertion through pydantic-settings, for all 76 fields.

    ``ResolvedNameTests`` above compares metadata against this module's own
    copy of the lookup rule, so it would keep agreeing with itself if
    pydantic-settings ever changed how it derives an env key. This test sets
    a real variable and reads the loaded attribute back, which is the property
    operators actually depend on.
    """

    # Fields whose validator or type rejects a generic probe value.
    CONSTRAINED = {
        "environment": ("staging", "staging"),
        "session_cookie_samesite": ("lax", "lax"),
        "secret_key": ("p" * 40, "p" * 40),
        "allowed_hosts": ("a.example,b.example", ["a.example", "b.example"]),
        "cors_origins": ("https://a.example", ["https://a.example"]),
        "label_mapping": ('{"Probe": 3}', {"Probe": 3}),
        "website_final_label_mapping": ('{"Probe": 3}', {"Probe": 3}),
    }

    def _probe(self, name, field):
        if name in self.CONSTRAINED:
            return self.CONSTRAINED[name]
        annotation = field.annotation
        if annotation is bool:
            return ("true", True)
        if annotation is int:
            return ("4242", 4242)
        if annotation is float:
            return ("13.5", 13.5)
        return (f"/probe/{name}", f"/probe/{name}")

    def test_every_field_binds_from_its_astrodash_variable(self):
        for name, field in Settings.model_fields.items():
            if name == "db_url":
                continue  # AnyUrl does not round-trip as a string; covered below
            raw, expected = self._probe(name, field)
            env = {resolved_env_name(name, field): raw}
            # template_path / line_list_path are rewritten by
            # resolve_data_paths_when_missing when the configured path is absent
            # and a same-named artifact exists under data_dir. Point data_dir at
            # nothing so the probe value survives and this test measures binding.
            if name in ("template_path", "line_list_path"):
                env["ASTRODASH_DATA_DIR"] = "/nonexistent-probe-root"
            with self.subTest(field=name), mock.patch.dict(
                os.environ, env, clear=False
            ):
                self.assertEqual(
                    getattr(Settings(), name),
                    expected,
                    f"{resolved_env_name(name, field)} did not reach {name}",
                )


class EnvBindingTests(SimpleTestCase):
    """End-to-end: setting the variable changes the loaded value."""

    def _load(self, **env):
        with mock.patch.dict(os.environ, env, clear=False):
            return Settings()

    def test_log_level_binds(self):
        """ASTRODASH_LOG_LEVEL reaches the field.

        Scope note: this asserts binding only. Nothing currently consumes
        ``settings.log_level`` -- ``config/logging.py:init_logging`` has no
        callers and Django's own LOGGING block hardcodes its levels -- so
        binding this field does not change what the app actually logs.
        """
        # The dev container itself sets ASTRODASH_LOG_LEVEL, so clear it
        # before asserting the default rather than reading ambient state.
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("ASTRODASH_LOG_LEVEL", None)
            self.assertEqual(Settings().log_level, "INFO")
        self.assertEqual(self._load(ASTRODASH_LOG_LEVEL="DEBUG").log_level, "DEBUG")

    def test_empty_value_is_ignored_rather_than_blanking_a_default(self):
        """env/.env.default uses blank placeholders (ASTRODASH_S3_REGION_NAME =)."""
        loaded = self._load(ASTRODASH_DATA_DIR="")
        self.assertEqual(loaded.data_dir, "/mnt/astrodash-data")

    def test_aliased_fields_are_settable_by_keyword(self):
        """validation_alias without populate_by_name silently drops keywords."""
        built = Settings(
            db_url="postgresql://kw@db.example:5432/astrodash",
            oned_cnn_z_model_path="/kw/model.pth",
        )
        self.assertEqual(built.oned_cnn_z_model_path, "/kw/model.pth")
        self.assertIsNotNone(built.db_url)
        self.assertEqual(built.model_extra, {})

    def test_int_field_binds(self):
        self.assertEqual(self._load(ASTRODASH_NW="2048").nw, 2048)

    def test_float_field_binds(self):
        loaded = self._load(ASTRODASH_USER_MODEL_RELIABILITY_THRESHOLD="0.99")
        self.assertEqual(loaded.user_model_reliability_threshold, 0.99)

    def test_bool_field_binds(self):
        loaded = self._load(ASTRODASH_TRANSFORMER_SELFATTN="true")
        self.assertTrue(loaded.transformer_selfattn)

    def test_list_field_binds_from_comma_string(self):
        """Complex fields are JSON-decoded before validators run.

        Without _AstrodashEnvSettingsSource this raises SettingsError
        instead of reaching ``split_str`` -- making the variable bind is
        only a fix if the documented comma form still works.
        """
        loaded = self._load(ASTRODASH_ALLOWED_HOSTS="a.example,b.example")
        self.assertEqual(loaded.allowed_hosts, ["a.example", "b.example"])

    def test_list_field_binds_from_json(self):
        loaded = self._load(ASTRODASH_CORS_ORIGINS='["https://x.example"]')
        self.assertEqual(loaded.cors_origins, ["https://x.example"])

    def test_dict_field_binds(self):
        loaded = self._load(ASTRODASH_LABEL_MAPPING='{"Ia": 7}')
        self.assertEqual(loaded.label_mapping, {"Ia": 7})

    def test_website_final_label_mapping_binds(self):
        loaded = self._load(ASTRODASH_WEBSITE_FINAL_LABEL_MAPPING='{"SN Ia": 3}')
        self.assertEqual(loaded.website_final_label_mapping, {"SN Ia": 3})

    def test_data_dir_binds(self):
        """The split-brain risk: initialize_data.py reads this via os.getenv."""
        loaded = self._load(ASTRODASH_DATA_DIR="/srv/astrodash-data")
        self.assertEqual(loaded.data_dir, "/srv/astrodash-data")

    def test_model_paths_bind(self):
        loaded = self._load(
            ASTRODASH_DASH_MODEL_PATH="/probe/dash.pth",
            ASTRODASH_TRANSFORMER_MODEL_PATH="/probe/transformer.pt",
            ASTRODASH_LATENT_Z_ENCODER_PATH="/probe/encoder.pt",
        )
        self.assertEqual(loaded.dash_model_path, "/probe/dash.pth")
        self.assertEqual(loaded.transformer_model_path, "/probe/transformer.pt")
        self.assertEqual(loaded.latent_z_encoder_path, "/probe/encoder.pt")

    def test_every_aliased_name_binds(self):
        """All five aliases, not just a sample -- these are deployed names."""
        probes = {
            "ASTRODASH_1DCNN_Z_MODEL_PATH": "oned_cnn_z_model_path",
            "ASTRODASH_1DCNN_Z_CLASS_MAPPING_PATH": "oned_cnn_z_class_mapping_path",
            "ASTRODASH_1DCNN_NOZ_MODEL_PATH": "oned_cnn_noz_model_path",
            "ASTRODASH_1DCNN_NOZ_CLASS_MAPPING_PATH": "oned_cnn_noz_class_mapping_path",
        }
        for env_name, field in probes.items():
            with self.subTest(env=env_name):
                value = f"/probe/{field}"
                self.assertEqual(getattr(self._load(**{env_name: value}), field), value)

    def test_aliased_database_url_binds(self):
        loaded = self._load(
            ASTRODASH_DATABASE_URL="postgresql://user@db.example:5432/astrodash"
        )
        self.assertIsNotNone(loaded.db_url)
        self.assertEqual(loaded.db_url.host, "db.example")
