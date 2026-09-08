# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Flow-level tests for OIDCProvider against a mock identity provider.

These cover what the provider does with a token response once the signature has
been checked: which claims become the Plane user, when the userinfo endpoint is
consulted, and which responses are refused. Token signature and claim validation
itself lives in test_oidc.py.
"""

import base64
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from plane.authentication.adapter.error import AuthenticationException
from plane.authentication.provider.oauth import oidc as provider_module
from plane.authentication.provider.oauth.oidc import OIDCProvider
from plane.authentication.utils import oidc as oidc_utils

ISSUER = "https://idp.example.com"
CLIENT_ID = "plane-client"
CLIENT_SECRET = "client-secret"
SUBJECT = "sub-abc"


def _generate_keypair():
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private_pem = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode()
    public_pem = (
        key.public_key()
        .public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
        .decode()
    )
    return private_pem, public_pem


PRIVATE_KEY, PUBLIC_KEY = _generate_keypair()

BASE_CONFIG = {
    "OIDC_ISSUER_URL": ISSUER,
    "OIDC_CLIENT_ID": CLIENT_ID,
    "OIDC_CLIENT_SECRET": CLIENT_SECRET,
    "OIDC_ALLOW_UNVERIFIED_EMAIL": "0",
}


def discovery(**overrides):
    document = {
        "issuer": ISSUER,
        "authorization_endpoint": f"{ISSUER}/authorize",
        "token_endpoint": f"{ISSUER}/token",
        "userinfo_endpoint": f"{ISSUER}/userinfo",
        "jwks_uri": f"{ISSUER}/jwks",
        "id_token_signing_alg_values_supported": ["RS256"],
    }
    document.update(overrides)
    return document


class FakeRequest:
    """Stands in for the Django request the provider reads the host from."""

    session = {}
    # save_user_data() copies REMOTE_ADDR and the user agent onto the user row, and both
    # users.last_login_ip and users.last_login_uagent are NOT NULL, so an empty META fails
    # the insert on any test that provisions a user.
    META = {"REMOTE_ADDR": "127.0.0.1", "HTTP_USER_AGENT": "pytest"}

    def is_secure(self):
        return True

    def get_host(self):
        return "plane.example.com"


@pytest.fixture(autouse=True)
def stub_jwks(monkeypatch):
    class _Key:
        key = PUBLIC_KEY

    class _Client:
        def get_signing_key_from_jwt(self, token):
            return _Key()

    monkeypatch.setattr(oidc_utils, "_get_jwk_client", lambda uri: _Client())


def make_id_token(claims=None, nonce=None):
    now = datetime.now(tz=timezone.utc)
    payload = {
        "iss": ISSUER,
        "sub": SUBJECT,
        "aud": CLIENT_ID,
        "iat": now,
        "exp": now + timedelta(minutes=5),
    }
    if nonce:
        payload["nonce"] = nonce
    payload.update(claims or {})
    return jwt.encode(payload, PRIVATE_KEY, algorithm="RS256")


def fake_config(keys, config=None):
    resolved = config or BASE_CONFIG
    return [resolved.get(key["key"], key.get("default")) for key in keys]


def build_provider(document=None, config=None, nonce=None, code="auth-code", state=None, is_space=False):
    with (
        patch.object(provider_module, "get_configuration_value", lambda keys: fake_config(keys, config)),
        patch.object(provider_module, "get_discovery_document", lambda issuer: document or discovery()),
    ):
        return OIDCProvider(request=FakeRequest(), code=code, state=state, nonce=nonce, is_space=is_space)


def run_flow(id_token_claims=None, userinfo=None, document=None, config=None, nonce=None):
    """Drive one full callback leg: token exchange, validation, claim mapping."""
    provider = build_provider(document, config, nonce)

    token_response = MagicMock()
    token_response.json.return_value = {
        "access_token": "access-token",
        "refresh_token": "refresh-token",
        "expires_in": 3600,
        "id_token": make_id_token(id_token_claims, nonce=nonce),
    }
    token_response.raise_for_status = lambda: None

    userinfo_response = MagicMock()
    userinfo_response.json.return_value = userinfo or {}
    userinfo_response.raise_for_status = lambda: None

    with (
        patch.object(provider_module, "get_configuration_value", lambda keys: fake_config(keys, config)),
        patch("plane.authentication.adapter.oauth.requests.post", return_value=token_response),
        patch("plane.authentication.adapter.oauth.requests.get", return_value=userinfo_response),
    ):
        provider.set_token_data()
        provider.set_user_data()

    return provider


@pytest.mark.unit
class TestClaimMapping:
    def test_user_data_comes_from_the_id_token(self):
        provider = run_flow(
            {
                "email": "ada@example.com",
                "email_verified": True,
                "given_name": "Ada",
                "family_name": "Lovelace",
                "picture": "https://example.com/ada.png",
            }
        )
        user = provider.user_data["user"]
        assert provider.user_data["email"] == "ada@example.com"
        # `sub`, not email: email can be reassigned, sub cannot.
        assert user["provider_id"] == SUBJECT
        assert user["first_name"] == "Ada"
        assert user["last_name"] == "Lovelace"
        assert user["avatar"] == "https://example.com/ada.png"
        assert user["is_password_autoset"] is True

    def test_full_name_is_split_when_given_name_is_absent(self):
        provider = run_flow(
            {"email": "alan@example.com", "email_verified": True, "name": "Alan Turing"},
            userinfo={"sub": SUBJECT},
        )
        user = provider.user_data["user"]
        assert user["first_name"] == "Alan"
        assert user["last_name"] == "Turing"

    def test_access_token_expiry_is_relative_to_now(self):
        provider = run_flow({"email": "ada@example.com", "email_verified": True, "name": "Ada"})
        assert provider.token_data["access_token_expired_at"] > datetime.now(tz=timezone.utc)


@pytest.mark.unit
class TestUnverifiedEmail:
    def test_unverified_email_is_rejected(self):
        with pytest.raises(AuthenticationException) as exc:
            run_flow({"email": "ada@example.com", "email_verified": False, "name": "Ada"})
        assert exc.value.error_message == "OAUTH_PROVIDER_UNVERIFIED_EMAIL"

    def test_absent_email_verified_claim_fails_closed(self):
        with pytest.raises(AuthenticationException) as exc:
            run_flow({"email": "ada@example.com", "name": "Ada"})
        assert exc.value.error_message == "OAUTH_PROVIDER_UNVERIFIED_EMAIL"

    def test_opt_out_allows_unverified_email(self):
        config = {**BASE_CONFIG, "OIDC_ALLOW_UNVERIFIED_EMAIL": "1"}
        provider = run_flow({"email": "ada@example.com", "name": "Ada"}, config=config)
        assert provider.user_data["email"] == "ada@example.com"


@pytest.mark.unit
class TestUserinfoFallback:
    def test_userinfo_fills_claims_the_id_token_omitted(self):
        provider = run_flow(
            {"email": "grace@example.com", "email_verified": True},
            userinfo={"sub": SUBJECT, "given_name": "Grace", "family_name": "Hopper"},
        )
        assert provider.user_data["user"]["first_name"] == "Grace"

    def test_userinfo_supplies_a_missing_email_verified(self):
        """An otherwise complete ID token that omits email_verified must still be
        topped up from userinfo rather than rejected. Providers differ on which claims
        reach the ID token, so rejecting here would fail a login that the userinfo
        call can satisfy."""
        provider = run_flow(
            {"email": "ada@example.com", "given_name": "Ada", "family_name": "Lovelace"},
            userinfo={"sub": SUBJECT, "email_verified": True},
        )
        assert provider.user_data["email"] == "ada@example.com"

    def test_userinfo_that_denies_verification_still_rejects(self):
        """Topping up from userinfo must not become a way around the check."""
        with pytest.raises(AuthenticationException) as exc:
            run_flow(
                {"email": "ada@example.com", "given_name": "Ada", "family_name": "Lovelace"},
                userinfo={"sub": SUBJECT, "email_verified": False},
            )
        assert exc.value.error_message == "OAUTH_PROVIDER_UNVERIFIED_EMAIL"

    def test_userinfo_is_not_called_when_the_id_token_suffices(self):
        """A complete ID token must not cost an extra network round trip."""
        provider = build_provider()
        token_response = MagicMock()
        token_response.json.return_value = {
            "access_token": "access-token",
            "expires_in": 3600,
            "id_token": make_id_token(
                {"email": "ada@example.com", "email_verified": True, "given_name": "Ada", "family_name": "Lovelace"}
            ),
        }
        token_response.raise_for_status = lambda: None

        with (
            patch.object(provider_module, "get_configuration_value", lambda keys: fake_config(keys)),
            patch("plane.authentication.adapter.oauth.requests.post", return_value=token_response),
            patch("plane.authentication.adapter.oauth.requests.get") as userinfo_get,
        ):
            provider.set_token_data()
            provider.set_user_data()

        userinfo_get.assert_not_called()

    def test_userinfo_for_another_subject_is_discarded(self):
        """A userinfo response that does not match the ID token must not be trusted."""
        provider = run_flow(
            {"email": "ada@example.com", "email_verified": True},
            userinfo={
                "sub": "a-different-subject",
                "given_name": "Mallory",
                "email": "mallory@evil.example.com",
            },
        )
        assert provider.user_data["email"] == "ada@example.com"
        assert provider.user_data["user"]["first_name"] != "Mallory"
        assert provider.user_data["user"]["provider_id"] == SUBJECT


@pytest.mark.unit
class TestClientAuthentication:
    def test_basic_auth_is_used_when_that_is_all_the_provider_accepts(self):
        provider = build_provider(discovery(token_endpoint_auth_methods_supported=["client_secret_basic"]))
        fields, headers = provider._token_request_auth()
        assert fields == {}
        credentials = base64.b64decode(headers["Authorization"].split()[1]).decode()
        assert credentials == f"{CLIENT_ID}:{CLIENT_SECRET}"

    def test_secret_goes_in_the_form_body_when_the_provider_offers_it(self):
        provider = build_provider(discovery(token_endpoint_auth_methods_supported=["client_secret_post"]))
        fields, headers = provider._token_request_auth()
        assert fields["client_secret"] == CLIENT_SECRET
        assert "Authorization" not in headers

    def test_post_is_preferred_when_the_provider_offers_both(self):
        provider = build_provider(
            discovery(token_endpoint_auth_methods_supported=["client_secret_basic", "client_secret_post"])
        )
        fields, headers = provider._token_request_auth()
        assert fields["client_secret"] == CLIENT_SECRET
        assert "Authorization" not in headers

    @pytest.mark.parametrize("advertised", [None, []], ids=["field-absent", "field-empty"])
    def test_an_unpublished_list_falls_back_to_basic_per_the_spec(self, advertised):
        """OIDC Discovery 1.0 §3: when token_endpoint_auth_methods_supported is
        omitted, "the default is client_secret_basic". A compliant provider that
        accepts only the default and publishes no list would reject a form-body
        secret, so an absent list is not a free choice."""
        document = discovery()
        if advertised is None:
            document.pop("token_endpoint_auth_methods_supported", None)
        else:
            document["token_endpoint_auth_methods_supported"] = advertised

        provider = build_provider(document)
        fields, headers = provider._token_request_auth()
        assert fields == {}
        credentials = base64.b64decode(headers["Authorization"].split()[1]).decode()
        assert credentials == f"{CLIENT_ID}:{CLIENT_SECRET}"


@pytest.mark.unit
class TestAuthorizationRequest:
    def test_authorization_url_carries_state_nonce_and_scope(self):
        provider = build_provider(state="state-1", nonce="nonce-1", code=None)
        url = provider.get_auth_url()
        assert "state=state-1" in url
        assert "nonce=nonce-1" in url
        assert "scope=openid+email+profile" in url
        assert "redirect_uri=https%3A%2F%2Fplane.example.com%2Fauth%2Foidc%2Fcallback%2F" in url

    def test_app_flow_calls_back_to_the_app_endpoint(self):
        provider = build_provider(state="state-1", nonce="nonce-1", code=None)
        assert provider.redirect_uri == "https://plane.example.com/auth/oidc/callback/"

    def test_spaces_flow_calls_back_to_the_spaces_endpoint(self):
        """The two flows keep separate session keys, so the IdP must return to the
        endpoint that started the login or the state/nonce lookup finds nothing."""
        provider = build_provider(state="state-1", nonce="nonce-1", code=None, is_space=True)
        assert provider.redirect_uri == "https://plane.example.com/auth/spaces/oidc/callback/"
        assert "redirect_uri=https%3A%2F%2Fplane.example.com%2Fauth%2Fspaces%2Foidc%2Fcallback%2F" in (
            provider.get_auth_url()
        )

    def test_missing_configuration_is_reported(self):
        config = {**BASE_CONFIG, "OIDC_CLIENT_SECRET": None}
        with pytest.raises(AuthenticationException) as exc:
            build_provider(config=config)
        assert exc.value.error_message == "OIDC_NOT_CONFIGURED"


@pytest.mark.unit
@pytest.mark.django_db
class TestSignupGating:
    """OIDC honours ENABLE_SIGNUP.

    There is no separate sign-up flow for OIDC — the same button serves login and
    registration — so hiding a sign-up button in the UI proves nothing here. The only
    thing standing between a disabled instance and a brand-new IdP identity is
    __check_signup() in the shared adapter, reached through complete_login_or_signup().
    """

    def _authenticate(self, email, enable_signup):
        """Drive the post-token half of the flow with a verified ID token for `email`."""
        provider = build_provider()
        provider.id_token_claims = {
            "sub": f"sub-for-{email}",
            "email": email,
            "email_verified": True,
            "given_name": "Ada",
            "family_name": "Lovelace",
        }
        provider.token_data = None  # skip Account creation; irrelevant to the gate

        with (
            patch.object(provider_module, "get_configuration_value", lambda keys: fake_config(keys)),
            patch(
                "plane.authentication.adapter.base.get_configuration_value",
                lambda keys: (enable_signup,),
            ),
        ):
            provider.set_user_data()
            return provider.complete_login_or_signup()

    def test_new_identity_is_refused_when_signup_is_disabled(self):
        from plane.db.models import User

        with pytest.raises(AuthenticationException) as exc:
            self._authenticate("stranger@example.com", enable_signup="0")

        assert exc.value.error_message == "SIGNUP_DISABLED"
        assert not User.objects.filter(email="stranger@example.com").exists()

    def test_new_identity_is_admitted_when_signup_is_enabled(self):
        user = self._authenticate("newcomer@example.com", enable_signup="1")
        assert user.email == "newcomer@example.com"

    def test_an_invited_address_is_admitted_even_while_signup_is_disabled(self):
        """The gate checks for a pending workspace invite before refusing."""
        from plane.db.models import Workspace, WorkspaceMemberInvite

        owner = self._authenticate("owner@example.com", enable_signup="1")
        workspace = Workspace.objects.create(name="Acme", slug="acme", owner=owner)
        WorkspaceMemberInvite.objects.create(email="invited@example.com", workspace=workspace, role=15, token="tok")

        user = self._authenticate("invited@example.com", enable_signup="0")
        assert user.email == "invited@example.com"

    def test_an_existing_user_can_still_sign_in_while_signup_is_disabled(self):
        """Gating registration must not lock out people who already have accounts."""
        existing = self._authenticate("regular@example.com", enable_signup="1")

        again = self._authenticate("regular@example.com", enable_signup="0")
        assert again.id == existing.id
