"""The gated-model access gate: entry links, the credential prompt, the scope.

A gated model (one whose definition declares ``requires_credential``) is
reachable only by redeeming a model-scoped entry link and presenting the shared
credential, which establishes a session scoped to that one model.

Every test here builds its gated model with ``dataclasses.replace`` over a real
definition plus a patched roster (KTD9): DASH becomes gated -- and therefore
unlisted, which the registry invariants require -- while Transformer is left
untouched so it keeps satisfying the listed, ungated active-default invariant.
Such a fixture never passes through the import-time validators, so nothing here
reloads modules.

These need a database: no session engine is configured, so sessions are
database-backed and anything driving the prompt or the scope through the test
client hits the sessions table.
"""

import os
import re
from contextlib import contextmanager
from dataclasses import replace
from io import StringIO
from unittest.mock import AsyncMock, MagicMock, patch

from django.contrib.auth import get_user_model
from django.core.management import CommandError, call_command
from django.http import HttpResponse
from django.test import TestCase
from django.urls import reverse

from astrodash.core import gate_config, model_access
from astrodash.infrastructure.ml import model_registry

# The shared credential and signing key every test configures. Neither may be
# blank or carry the committed ``django-insecure-`` prefix, or the gate reads
# them as unconfigured.
GATE_CREDENTIAL = "review-window-access-code"
GATE_SIGNING_KEY = "test-entry-link-signing-key"
GATE_LINK_BASE_URL = "https://astrodash-dev.example.org"


def gated_roster(model_id="dash"):
    """Return a roster in which one built-in model is gated.

    Args:
        model_id: The built-in id to gate. It is made unlisted at the same
            time, because the registry forbids a gated model from being listed.

    Returns:
        tuple: A ``MODELS``-shaped tuple suitable for ``patch.object``.
    """
    return tuple(
        replace(m, listed=False, requires_credential=True) if m.id == model_id else m
        for m in model_registry.MODELS
    )


@contextmanager
def gate_configured(
    credential=GATE_CREDENTIAL, ttl_seconds="3600", signing_key=GATE_SIGNING_KEY
):
    """Configure the gate's deployment values for the duration of the block.

    The normalized configuration is patched in rather than driven through the
    environment, because the entry-link signing key *is* ``SECRET_KEY``: moving
    the real setting would re-sign the test client's session cookie mid-test and
    every session assertion here would read an empty session instead of the one
    the gate wrote. ``gate_config``'s own normalization is covered by the
    registry tests. The link host is a separate value that no session depends
    on, so it stays an environment read.

    Args:
        credential: The shared credential an operator would configure.
        ttl_seconds: The entry-link expiry window, as an operator sets it.
        signing_key: The key entry links are signed with.

    Yields:
        None.
    """
    configuration = {
        gate_config.CREDENTIAL_ENV_VAR: credential,
        gate_config.LINK_TTL_ENV_VAR: ttl_seconds,
        gate_config.SIGNING_KEY_NAME: signing_key,
    }
    with patch.object(
        model_access, "gate_configuration", return_value=configuration
    ), patch.dict(os.environ, {gate_config.LINK_BASE_URL_ENV_VAR: GATE_LINK_BASE_URL}):
        yield


@contextmanager
def gated_gate(model_id="dash", **config):
    """Patch in a gated roster *and* the gate configuration together.

    Args:
        model_id: The built-in id to gate.
        **config: Passed through to :func:`gate_configured`.

    Yields:
        None.
    """
    with patch.object(model_registry, "MODELS", gated_roster(model_id)):
        with gate_configured(**config):
            yield


def gate_url(token):
    """Return the entry-link path carrying a token."""
    return reverse("astrodash:model_gate", args=[token])


def classify_post(model):
    """Return a valid classify-form payload naming a model.

    Args:
        model: The value to put in the form's model field. Inside a scoped
            flow this is exactly the field an attacker would alter, so tests
            vary it independently of the scope.

    Returns:
        dict: The POST data.
    """
    return {
        "supernova_name": "SN2011fe",
        "model": model,
        "smoothing": 0,
        "min_wave": 3500,
        "max_wave": 10000,
    }


@contextmanager
def mocked_classification(model_type):
    """Run the classify view without model weights or network access.

    Args:
        model_type: The model the mocked classification reports having run.

    Yields:
        The mocked classification service, so a test can read back which model
        the view actually asked it to run.
    """
    processed = MagicMock()
    processed.x = [3000.0, 5000.0, 9000.0]
    processed.y = [1.0, 2.0, 1.0]

    classification = MagicMock()
    classification.model_type = model_type
    classification.results = {"best_matches": [], "embedding": [0.0] * 1024}

    classification_svc = MagicMock(
        classify_spectrum=AsyncMock(return_value=classification)
    )
    with patch(
        "astrodash.ui_views.get_spectrum_service",
        return_value=MagicMock(get_spectrum_data=AsyncMock(return_value=MagicMock())),
    ), patch(
        "astrodash.ui_views.get_spectrum_processing_service",
        return_value=MagicMock(
            process_spectrum_with_params=AsyncMock(return_value=processed)
        ),
    ), patch(
        "astrodash.ui_views.get_classification_service",
        return_value=classification_svc,
    ), patch(
        "astrodash.ui_views.render", return_value=HttpResponse(b"")
    ):
        yield classification_svc


class EntryLinkTokenTests(TestCase):
    """R6/R8/R28: what a minted token carries and when it stops resolving."""

    def test_minted_link_resolves_to_its_model(self):
        with gated_gate():
            token = model_access.mint_entry_link("dash")
            link = model_access.redeem_entry_link(token)
        self.assertEqual(link.model_id, "dash")

    def test_deadline_is_stamped_at_mint_not_evaluated_later(self):
        """KTD2: shortening the window cannot move an outstanding link's deadline."""
        with gated_gate(ttl_seconds="3600"), patch.object(
            model_access, "_now", return_value=1000.0
        ):
            token = model_access.mint_entry_link("dash")
        # The window is shortened after the link was minted; the link keeps the
        # deadline it was stamped with.
        with gated_gate(ttl_seconds="60"), patch.object(
            model_access, "_now", return_value=1000.0
        ):
            link = model_access.redeem_entry_link(token)
        self.assertEqual(link.expires_at, 1000.0 + 3600)

    def test_expired_link_is_refused(self):
        with gated_gate(ttl_seconds="60"), patch.object(
            model_access, "_now", return_value=1000.0
        ):
            token = model_access.mint_entry_link("dash")
        with gated_gate(), patch.object(model_access, "_now", return_value=5000.0):
            with self.assertRaises(model_access.EntryLinkRefused):
                model_access.redeem_entry_link(token)

    def test_tampered_token_is_refused(self):
        with gated_gate():
            token = model_access.mint_entry_link("dash")
            with self.assertRaises(model_access.EntryLinkRefused):
                model_access.redeem_entry_link(token[:-2] + "xy")

    def test_link_signed_with_another_key_is_refused(self):
        with gated_gate():
            token = model_access.mint_entry_link("dash")
        with gated_gate(signing_key="a-different-signing-key"):
            with self.assertRaises(model_access.EntryLinkRefused):
                model_access.redeem_entry_link(token)

    def test_minting_without_configuration_fails_closed(self):
        unconfigured = {
            gate_config.CREDENTIAL_ENV_VAR: None,
            gate_config.LINK_TTL_ENV_VAR: None,
            gate_config.SIGNING_KEY_NAME: None,
        }
        with patch.object(
            model_access, "gate_configuration", return_value=unconfigured
        ):
            with self.assertRaises(model_access.GateNotConfigured):
                model_access.mint_entry_link("dash")

    def test_committed_signing_key_refuses_to_mint(self):
        """R34: a key published in the repository signs nothing.

        Read through the real configuration path, so the committed
        ``django-insecure-`` default this deployment still carries is what makes
        it fail.
        """
        env = {
            gate_config.CREDENTIAL_ENV_VAR: GATE_CREDENTIAL,
            gate_config.LINK_TTL_ENV_VAR: "3600",
        }
        with patch.dict(os.environ, env):
            with self.assertRaises(model_access.GateNotConfigured):
                model_access.mint_entry_link("dash")


class CredentialPromptTests(TestCase):
    """R7/R8/AE2/AE11: what an entry link shows, and what a refusal discloses."""

    # A marker the refusal template carries, proving the response is our page
    # and not a framework default error page.
    REFUSAL_MARKER = 'id="model-gate-refused"'
    PROMPT_MARKER = 'id="model-gate-credential"'

    def _mint(self, ttl_seconds="3600", now=1000.0):
        with gated_gate(ttl_seconds=ttl_seconds), patch.object(
            model_access, "_now", return_value=now
        ):
            return model_access.mint_entry_link("dash")

    def test_unexpired_link_renders_the_credential_prompt(self):
        token = self._mint()
        with gated_gate(), patch.object(model_access, "_now", return_value=1001.0):
            resp = self.client.get(gate_url(token))
        self.assertEqual(resp.status_code, 200)
        self.assertIn(self.PROMPT_MARKER, resp.content.decode())

    def test_expired_link_renders_the_refusal_and_names_no_model(self):
        """AE2: refused, and the response reveals nothing about the model."""
        token = self._mint(ttl_seconds="60")
        with gated_gate(), patch.object(model_access, "_now", return_value=9000.0):
            resp = self.client.get(gate_url(token))
        body = resp.content.decode()
        self.assertEqual(resp.status_code, 403)
        self.assertIn(self.REFUSAL_MARKER, body)
        self.assertNotIn(self.PROMPT_MARKER, body)
        self.assertNotIn("dash", body.lower().replace("astrodash", ""))

    def test_tampered_token_is_indistinguishable_from_the_expired_case(self):
        token = self._mint()
        with gated_gate(), patch.object(model_access, "_now", return_value=1001.0):
            tampered = self.client.get(gate_url(token[:-2] + "xy"))
        expired_token = self._mint(ttl_seconds="60")
        with gated_gate(), patch.object(model_access, "_now", return_value=9000.0):
            expired = self.client.get(gate_url(expired_token))
        self.assertEqual(tampered.status_code, expired.status_code)
        self.assertEqual(tampered.content, expired.content)

    def test_correct_credential_scopes_the_session_to_that_model(self):
        token = self._mint()
        with gated_gate(), patch.object(model_access, "_now", return_value=1001.0):
            resp = self.client.post(
                gate_url(token), data={"credential": GATE_CREDENTIAL}
            )
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(resp["Location"], reverse("astrodash:classify"))
        session = self.client.session
        self.assertEqual(session[model_access.SCOPE_MODEL_KEY], "dash")
        self.assertEqual(session[model_access.SCOPE_DEADLINE_KEY], 1000.0 + 3600)

    def test_incorrect_credential_redisplays_the_prompt_and_permits_retry(self):
        """AE11: a mistyped credential on a valid link is retryable."""
        token = self._mint()
        with gated_gate(), patch.object(model_access, "_now", return_value=1001.0):
            wrong = self.client.post(gate_url(token), data={"credential": "not-it"})
            body = wrong.content.decode()
            self.assertEqual(wrong.status_code, 200)
            self.assertIn(self.PROMPT_MARKER, body)
            self.assertNotIn(self.REFUSAL_MARKER, body)
            self.assertNotIn(model_access.SCOPE_MODEL_KEY, self.client.session)
            # The same link still works on the next attempt.
            ok = self.client.post(gate_url(token), data={"credential": GATE_CREDENTIAL})
        self.assertEqual(ok.status_code, 302)
        self.assertEqual(self.client.session[model_access.SCOPE_MODEL_KEY], "dash")

    def test_wrong_credential_error_names_no_model(self):
        token = self._mint()
        with gated_gate(), patch.object(model_access, "_now", return_value=1001.0):
            resp = self.client.post(gate_url(token), data={"credential": "not-it"})
        body = resp.content.decode()
        self.assertNotIn("dash", body.lower().replace("astrodash", ""))

    def test_link_lapsing_between_prompt_and_submit_is_refused(self):
        token = self._mint(ttl_seconds="60")
        with gated_gate(ttl_seconds="60"), patch.object(
            model_access, "_now", return_value=1001.0
        ):
            prompt = self.client.get(gate_url(token))
        self.assertEqual(prompt.status_code, 200)
        with gated_gate(ttl_seconds="60"), patch.object(
            model_access, "_now", return_value=9000.0
        ):
            resp = self.client.post(
                gate_url(token), data={"credential": GATE_CREDENTIAL}
            )
        self.assertEqual(resp.status_code, 403)
        self.assertIn(self.REFUSAL_MARKER, resp.content.decode())
        self.assertNotIn(model_access.SCOPE_MODEL_KEY, self.client.session)

    def test_published_model_link_redirects_into_the_public_flow(self):
        """A reviewer is never locked out of a model that has become public."""
        token = self._mint()
        # No gated roster this time: the model has been published, so its
        # definition no longer requires a credential.
        with gate_configured(), patch.object(model_access, "_now", return_value=1001.0):
            resp = self.client.get(gate_url(token))
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(resp["Location"], reverse("astrodash:classify"))
        session = self.client.session
        self.assertEqual(session["selected_model_type"], "dash")
        self.assertNotIn(model_access.SCOPE_MODEL_KEY, session)


class RedeemClearsPriorStateTests(TestCase):
    """R33/AE15: redeeming starts from a clean session, scope keys written last."""

    def _redeem_over(self, session_state):
        """Seed a session, then redeem a fresh link over it.

        Args:
            session_state: Mapping of session keys to seed before redeeming.

        Returns:
            The session after the redemption.
        """
        session = self.client.session
        session.update(session_state)
        session.save()
        with gated_gate(), patch.object(model_access, "_now", return_value=1000.0):
            token = model_access.mint_entry_link("dash")
            resp = self.client.post(
                gate_url(token), data={"credential": GATE_CREDENTIAL}
            )
        self.assertEqual(resp.status_code, 302)
        return self.client.session

    def test_redeem_clears_a_prior_user_model_selection(self):
        session = self._redeem_over(
            {"selected_model_type": "user_uploaded", "selected_model_id": "um-1"}
        )
        self.assertEqual(session[model_access.SCOPE_MODEL_KEY], "dash")
        self.assertIsNone(session.get("selected_model_id"))

    def test_redeem_clears_prior_classification_artifacts(self):
        session = self._redeem_over(
            {
                "classify_dash_embedding": [0.0] * 1024,
                "classify_results": {"best_matches": []},
                "classify_model_type": "dash",
            }
        )
        for key in (
            "classify_dash_embedding",
            "classify_results",
            "classify_model_type",
        ):
            self.assertNotIn(key, session)


class ScopeDeadlineTests(TestCase):
    """R28/AE10: the stored deadline is absolute and immovable."""

    def test_session_write_after_grant_does_not_move_the_deadline(self):
        with gated_gate(), patch.object(model_access, "_now", return_value=1000.0):
            token = model_access.mint_entry_link("dash")
            self.client.post(gate_url(token), data={"credential": GATE_CREDENTIAL})
            granted = self.client.session[model_access.SCOPE_DEADLINE_KEY]
            # A later request that writes to the session must not re-arm the
            # deadline: an idle-timeout implementation would.
            with patch.object(model_access, "_now", return_value=2000.0):
                self.client.get(reverse("astrodash:classify"))
        self.assertEqual(self.client.session[model_access.SCOPE_DEADLINE_KEY], granted)
        self.assertEqual(granted, 1000.0 + 3600)


class ScopeEnforcementTests(TestCase):
    """R9/R11/R12: every surface that can run a gated model consults the scope."""

    SCOPED_CONTROL_MARKER = 'id="scoped-model-name"'

    def _redeem(self, now=1000.0, ttl_seconds="3600", seed=None):
        """Establish a scope by redeeming a fresh link.

        Args:
            now: The POSIX timestamp to mint and redeem at.
            ttl_seconds: The configured window.
            seed: Optional session state to seed before redeeming.

        Returns:
            The absolute deadline the scope was granted with.
        """
        if seed:
            session = self.client.session
            session.update(seed)
            session.save()
        with gated_gate(ttl_seconds=ttl_seconds), patch.object(
            model_access, "_now", return_value=now
        ):
            token = model_access.mint_entry_link("dash")
            resp = self.client.post(
                gate_url(token), data={"credential": GATE_CREDENTIAL}
            )
        self.assertEqual(resp.status_code, 302)
        return self.client.session[model_access.SCOPE_DEADLINE_KEY]

    def _seed_selection(self, **extra):
        session = self.client.session
        session["selected_model_type"] = "dash"
        session.update(extra)
        session.save()

    # --- refused without a scope ---

    def test_gated_classification_view_is_refused_without_a_scope(self):
        self._seed_selection()
        with gated_gate(), patch.object(model_access, "_now", return_value=1000.0):
            resp = self.client.get(reverse("astrodash:classify"))
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(
            resp["Location"].startswith(reverse("astrodash:model_selection")),
            resp["Location"],
        )

    def test_gated_surface_page_route_is_refused_without_a_scope(self):
        self._seed_selection()
        with gated_gate(), patch.object(model_access, "_now", return_value=1000.0):
            resp = self.client.get(reverse("astrodash:dash_twins"))
        self.assertEqual(resp.status_code, 403)

    def test_gated_surface_data_route_is_refused_without_a_scope(self):
        self._seed_selection()
        with gated_gate(), patch.object(model_access, "_now", return_value=1000.0):
            resp = self.client.get(reverse("astrodash:dash_twins_data"))
        self.assertEqual(resp.status_code, 403)

    def test_gated_surface_search_route_is_refused_without_a_scope(self):
        self._seed_selection(
            classify_model_type="dash", classify_dash_embedding=[0.0] * 1024
        )
        with gated_gate(), patch.object(model_access, "_now", return_value=1000.0):
            resp = self.client.get(reverse("astrodash:twins_search"))
        self.assertEqual(resp.status_code, 403)

    # --- the model control in a scoped session ---

    def test_scoped_session_renders_the_model_control_disabled_and_named(self):
        self._redeem()
        with gated_gate(), patch.object(model_access, "_now", return_value=1001.0):
            resp = self.client.get(reverse("astrodash:classify"))
        body = resp.content.decode()
        self.assertEqual(resp.status_code, 200)
        self.assertIn(self.SCOPED_CONTROL_MARKER, body)
        control = re.search(r"<input[^>]*id=\"scoped-model-name\"[^>]*>", body).group(0)
        self.assertIn("disabled", control)
        self.assertIn(model_registry.get_definition("dash").title, control)
        # The dropdown is not offered alongside it.
        self.assertNotIn('id="id_model"', body)

    # --- the model that actually runs ---

    def test_scoped_submission_validates_though_the_model_is_unlisted(self):
        """A gated model is unlisted, so its id is in no listed choice set."""
        self._redeem()
        with gated_gate(), patch.object(
            model_access, "_now", return_value=1001.0
        ), mocked_classification("dash") as classification_svc:
            self.client.post(reverse("astrodash:classify"), data=classify_post("dash"))
        self.assertEqual(
            classification_svc.classify_spectrum.await_args.kwargs["model_type"], "dash"
        )

    def test_altered_request_still_runs_the_scoped_model(self):
        """AE3: the request cannot be moved to another model."""
        self._redeem()
        with gated_gate(), patch.object(
            model_access, "_now", return_value=1001.0
        ), mocked_classification("dash") as classification_svc:
            self.client.post(
                reverse("astrodash:classify"), data=classify_post("transformer")
            )
        self.assertEqual(
            classification_svc.classify_spectrum.await_args.kwargs["model_type"], "dash"
        )

    def test_prior_uploaded_selection_does_not_survive_into_the_scope(self):
        """AE15: a stale selection cannot displace the scope."""
        self._redeem(
            seed={"selected_model_type": "user_uploaded", "selected_model_id": "um-1"}
        )
        with gated_gate(), patch.object(
            model_access, "_now", return_value=1001.0
        ), mocked_classification("dash") as classification_svc:
            self.client.post(reverse("astrodash:classify"), data=classify_post("dash"))
        kwargs = classification_svc.classify_spectrum.await_args.kwargs
        self.assertEqual(kwargs["model_type"], "dash")
        self.assertIsNone(kwargs["user_model_id"])

    # --- the deadline is a lifetime, not an idle timeout ---

    def test_continuous_classification_still_loses_access_at_the_deadline(self):
        """AE10: activity must not extend the deadline."""
        deadline = self._redeem(now=1000.0, ttl_seconds="3600")
        for tick in (1001.0, 2000.0, 3000.0, 4000.0):
            with gated_gate(), patch.object(
                model_access, "_now", return_value=tick
            ), mocked_classification("dash"):
                resp = self.client.post(
                    reverse("astrodash:classify"), data=classify_post("dash")
                )
            self.assertEqual(resp.status_code, 200, f"refused early at {tick}")
            self.assertEqual(
                self.client.session[model_access.SCOPE_DEADLINE_KEY], deadline
            )
        with gated_gate(), patch.object(
            model_access, "_now", return_value=deadline + 1
        ):
            resp = self.client.get(reverse("astrodash:classify"))
        self.assertEqual(resp.status_code, 403)
        self.assertIn(CredentialPromptTests.REFUSAL_MARKER, resp.content.decode())
        self.assertNotIn(model_access.SCOPE_MODEL_KEY, self.client.session)

    def test_lapsed_scope_refusal_names_no_model(self):
        deadline = self._redeem()
        with gated_gate(), patch.object(
            model_access, "_now", return_value=deadline + 1
        ):
            resp = self.client.get(reverse("astrodash:classify"))
        body = resp.content.decode()
        self.assertNotIn("dash", body.lower().replace("astrodash", ""))

    def test_scope_survives_django_login_with_its_deadline_intact(self):
        deadline = self._redeem()
        user = get_user_model().objects.create_user(
            username="reviewer", password="not-the-gate-credential"
        )
        self.client.force_login(user)
        session = self.client.session
        self.assertEqual(session[model_access.SCOPE_MODEL_KEY], "dash")
        self.assertEqual(session[model_access.SCOPE_DEADLINE_KEY], deadline)
        with gated_gate(), patch.object(model_access, "_now", return_value=1001.0):
            resp = self.client.get(reverse("astrodash:classify"))
        self.assertEqual(resp.status_code, 200)


class UngatedFlowUnaffectedTests(TestCase):
    """R21: with no gated model anywhere, nothing about the gate is visible."""

    def test_public_classify_page_still_renders_the_model_dropdown(self):
        session = self.client.session
        session["selected_model_type"] = "dash"
        session.save()
        resp = self.client.get(reverse("astrodash:classify"))
        body = resp.content.decode()
        self.assertEqual(resp.status_code, 200)
        self.assertIn('id="id_model"', body)
        self.assertNotIn(ScopeEnforcementTests.SCOPED_CONTROL_MARKER, body)

    def test_public_twins_routes_still_served_for_dash(self):
        session = self.client.session
        session["selected_model_type"] = "dash"
        session.save()
        self.assertEqual(
            self.client.get(reverse("astrodash:dash_twins")).status_code, 200
        )


class MintCommandTests(TestCase):
    """R10: minting is operator-only, and no route mints a link."""

    def _mint_via_command(self, *args):
        out = StringIO()
        with gated_gate(), patch.object(model_access, "_now", return_value=1000.0):
            call_command("mint_model_link", *args, stdout=out)
        return out.getvalue().strip()

    def test_command_prints_a_redeemable_link(self):
        printed = self._mint_via_command("dash")
        self.assertTrue(printed.startswith(GATE_LINK_BASE_URL), printed)
        path = printed[len(GATE_LINK_BASE_URL) :]
        with gated_gate(), patch.object(model_access, "_now", return_value=1001.0):
            resp = self.client.get(path)
        self.assertEqual(resp.status_code, 200)
        self.assertIn(CredentialPromptTests.PROMPT_MARKER, resp.content.decode())

    def test_command_honors_an_explicit_window(self):
        printed = self._mint_via_command("dash", "--ttl-seconds", "120")
        token = printed.rstrip("/").rsplit("/", 1)[-1]
        with gated_gate(), patch.object(model_access, "_now", return_value=1000.0):
            link = model_access.redeem_entry_link(token)
        self.assertEqual(link.expires_at, 1000.0 + 120)

    def test_command_refuses_an_ungated_model(self):
        with gate_configured():
            with self.assertRaises(CommandError):
                call_command("mint_model_link", "transformer", stdout=StringIO())

    def test_command_refuses_an_unknown_model(self):
        with gated_gate():
            with self.assertRaises(CommandError):
                call_command("mint_model_link", "no-such-model", stdout=StringIO())

    def test_no_url_route_mints_a_link(self):
        from astrodash import urls as astrodash_urls

        names = [p.name for p in astrodash_urls.urlpatterns]
        self.assertNotIn("mint_model_link", names)
        for name in names:
            self.assertNotIn("mint", name)
        # The gate route exists, and it is the redeem side only.
        self.assertIn("model_gate", names)

    def test_command_without_a_link_base_url_fails_closed(self):
        with gated_gate():
            os.environ.pop(gate_config.LINK_BASE_URL_ENV_VAR, None)
            with self.assertRaises(CommandError):
                call_command("mint_model_link", "dash", stdout=StringIO())


class SessionCookieSecurityTests(TestCase):
    """The session now carries authorization, not just a preference."""

    def test_session_cookie_is_marked_secure(self):
        from django.conf import settings

        self.assertTrue(settings.SESSION_COOKIE_SECURE)
        # Pinned alongside the CSRF cookie's flag, which was already set.
        self.assertTrue(settings.CSRF_COOKIE_SECURE)


class RefusalCopyTests(TestCase):
    """The refusal is the first thing an anonymous reviewer may ever see."""

    def test_refusal_is_not_a_framework_default_error_page(self):
        with gated_gate():
            resp = self.client.get(gate_url("not-a-real-token"))
        body = resp.content.decode()
        self.assertEqual(resp.status_code, 403)
        self.assertIn(CredentialPromptTests.REFUSAL_MARKER, body)
        # Rendered through the site's own layout, not Django's bare 403 page.
        self.assertNotIn("Forbidden</h1>", body)
        self.assertTrue(re.search(r"<html", body, re.IGNORECASE))
