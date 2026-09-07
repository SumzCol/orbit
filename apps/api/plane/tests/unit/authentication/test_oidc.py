# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""ID token validation tests for the generic OIDC provider.

The ID token is the only thing proving who the user is, so every rejection path
here is a security control rather than input validation. The forged-HS256 case in
particular guards the classic algorithm-confusion attack: the issuer's public key
is published in its JWKS, so if a symmetric algorithm were ever accepted, anyone
could mint a valid-looking token by using that public key as the HMAC secret.
"""

import base64
import hashlib
import hmac
import json
import time
from datetime import datetime, timedelta, timezone

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from plane.authentication.adapter.error import AuthenticationException
from plane.authentication.utils import oidc as oidc_utils

ISSUER = "https://idp.example.com"
CLIENT_ID = "plane-client"


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
OTHER_PRIVATE_KEY, _ = _generate_keypair()

DISCOVERY = {
    "issuer": ISSUER,
    "authorization_endpoint": f"{ISSUER}/authorize",
    "token_endpoint": f"{ISSUER}/token",
    "jwks_uri": f"{ISSUER}/jwks",
    "id_token_signing_alg_values_supported": ["RS256"],
}


@pytest.fixture(autouse=True)
def stub_jwks(monkeypatch):
    """Serve the public key directly instead of fetching the issuer's JWKS."""

    class _Key:
        key = PUBLIC_KEY

    class _Client:
        def get_signing_key_from_jwt(self, token):
            return _Key()

    monkeypatch.setattr(oidc_utils, "_get_jwk_client", lambda uri: _Client())


def make_token(claims=None, key=PRIVATE_KEY):
    now = datetime.now(tz=timezone.utc)
    payload = {
        "iss": ISSUER,
        "sub": "user-123",
        "aud": CLIENT_ID,
        "iat": now,
        "exp": now + timedelta(minutes=5),
    }
    payload.update(claims or {})
    return jwt.encode(payload, key, algorithm="RS256")


def validate(token, nonce=None):
    return oidc_utils.validate_id_token(token, DISCOVERY, CLIENT_ID, nonce=nonce)


@pytest.mark.unit
class TestValidateIdToken:
    def test_valid_token_is_accepted(self):
        claims = validate(make_token())
        assert claims["sub"] == "user-123"

    def test_missing_token_is_rejected(self):
        with pytest.raises(AuthenticationException):
            validate(None)

    def test_expired_token_is_rejected(self):
        expired = make_token({"exp": datetime.now(tz=timezone.utc) - timedelta(hours=1)})
        with pytest.raises(AuthenticationException):
            validate(expired)

    def test_wrong_audience_is_rejected(self):
        with pytest.raises(AuthenticationException):
            validate(make_token({"aud": "a-different-client"}))

    def test_wrong_issuer_is_rejected(self):
        with pytest.raises(AuthenticationException):
            validate(make_token({"iss": "https://evil.example.com"}))

    def test_token_signed_by_another_key_is_rejected(self):
        with pytest.raises(AuthenticationException):
            validate(make_token(key=OTHER_PRIVATE_KEY))

    def test_missing_sub_is_rejected(self):
        now = datetime.now(tz=timezone.utc)
        token = jwt.encode(
            {"iss": ISSUER, "aud": CLIENT_ID, "iat": now, "exp": now + timedelta(minutes=5)},
            PRIVATE_KEY,
            algorithm="RS256",
        )
        with pytest.raises(AuthenticationException):
            validate(token)

    def test_forged_hs256_token_is_rejected(self):
        """Algorithm confusion: HMAC the token with the issuer's public key.

        Assembled by hand because PyJWT's encode() refuses to build it — which is
        precisely what an attacker would do.
        """

        def b64u(raw):
            return base64.urlsafe_b64encode(raw).rstrip(b"=")

        now = int(time.time())
        header = b64u(json.dumps({"alg": "HS256", "typ": "JWT", "kid": "k1"}).encode())
        payload = b64u(
            json.dumps({"iss": ISSUER, "sub": "attacker", "aud": CLIENT_ID, "iat": now, "exp": now + 300}).encode()
        )
        signing_input = header + b"." + payload
        signature = b64u(hmac.new(PUBLIC_KEY.encode(), signing_input, hashlib.sha256).digest())
        forged = (signing_input + b"." + signature).decode()

        with pytest.raises(AuthenticationException):
            validate(forged)


@pytest.mark.unit
class TestNonceBinding:
    def test_matching_nonce_is_accepted(self):
        assert validate(make_token({"nonce": "abc"}), nonce="abc")["nonce"] == "abc"

    def test_mismatched_nonce_is_rejected(self):
        with pytest.raises(AuthenticationException):
            validate(make_token({"nonce": "abc"}), nonce="xyz")

    def test_absent_nonce_claim_is_rejected_when_one_was_sent(self):
        with pytest.raises(AuthenticationException):
            validate(make_token(), nonce="abc")


@pytest.mark.unit
class TestMultipleAudiences:
    def test_correct_azp_is_accepted(self):
        token = make_token({"aud": [CLIENT_ID, "other-client"], "azp": CLIENT_ID})
        assert validate(token)["sub"] == "user-123"

    def test_azp_naming_another_client_is_rejected(self):
        token = make_token({"aud": [CLIENT_ID, "other-client"], "azp": "other-client"})
        with pytest.raises(AuthenticationException):
            validate(token)

    def test_missing_azp_is_rejected(self):
        token = make_token({"aud": [CLIENT_ID, "other-client"]})
        with pytest.raises(AuthenticationException):
            validate(token)


@pytest.mark.unit
class TestDiscoveryEndpointSchemes:
    """Every endpoint in the document is a separate URL and may point anywhere.

    token_endpoint receives the authorization code together with the client secret,
    and jwks_uri supplies the keys every signature is checked against, so a document
    advertising http:// for either is refused rather than followed.
    """

    @pytest.fixture(autouse=True)
    def isolated_cache(self, monkeypatch):
        """Give each test its own discovery cache.

        The module caches documents through Django's cache, which under the test
        settings is Redis. Reaching for it would make these tests order-dependent on
        each other and dependent on a running backend, neither of which belongs in a
        unit test.
        """

        class _Cache:
            def __init__(self):
                self.store = {}

            def get(self, key):
                return self.store.get(key)

            def set(self, key, value, ttl=None):
                self.store[key] = value

        monkeypatch.setattr(oidc_utils, "cache", _Cache())

    def _fetch(self, document, monkeypatch):
        class _Response:
            @staticmethod
            def raise_for_status():
                return None

            @staticmethod
            def json():
                return document

        monkeypatch.setattr(oidc_utils.requests, "get", lambda *a, **k: _Response())
        return oidc_utils.get_discovery_document(ISSUER)

    def test_an_https_document_is_accepted(self, monkeypatch):
        assert self._fetch(DISCOVERY, monkeypatch)["issuer"] == ISSUER

    @pytest.mark.parametrize(
        "field",
        ["authorization_endpoint", "token_endpoint", "jwks_uri", "userinfo_endpoint"],
    )
    def test_a_plaintext_endpoint_is_refused(self, field, monkeypatch):
        document = {**DISCOVERY, "userinfo_endpoint": f"{ISSUER}/userinfo"}
        document[field] = document[field].replace("https://", "http://")
        with pytest.raises(AuthenticationException) as exc:
            self._fetch(document, monkeypatch)
        assert exc.value.error_message == "OIDC_OAUTH_PROVIDER_ERROR"


@pytest.mark.unit
class TestSigningAlgorithms:
    def test_symmetric_only_provider_is_refused(self):
        document = {**DISCOVERY, "id_token_signing_alg_values_supported": ["HS256", "none"]}
        with pytest.raises(AuthenticationException):
            oidc_utils.get_signing_algorithms(document)

    def test_asymmetric_algorithms_are_kept(self):
        document = {**DISCOVERY, "id_token_signing_alg_values_supported": ["RS256", "HS256", "ES256"]}
        assert oidc_utils.get_signing_algorithms(document) == ["RS256", "ES256"]


@pytest.mark.unit
class TestNormalizeIssuer:
    def test_trailing_slash_is_stripped(self):
        assert oidc_utils.normalize_issuer("https://idp.example.com/") == "https://idp.example.com"

    @pytest.mark.parametrize(
        "issuer",
        ["", None, "http://idp.example.com", "https://idp.example.com?x=1", "https://idp.example.com#f", "https://"],
        ids=["empty", "none", "plaintext", "querystring", "fragment", "no-host"],
    )
    def test_a_bad_configured_issuer_reads_as_misconfiguration(self, issuer):
        """The admin typed this, so the sign-in page must say "contact your
        administrator" rather than "try again" — the latter sends someone chasing a
        transient fault that will never clear."""
        with pytest.raises(AuthenticationException) as exc:
            oidc_utils.normalize_issuer(issuer)
        assert exc.value.error_message == "OIDC_NOT_CONFIGURED"

    @pytest.mark.parametrize("issuer", ["", "http://idp.example.com"], ids=["empty", "plaintext"])
    def test_a_bad_issuer_inside_a_discovery_document_blames_the_provider(self, issuer):
        """Same validation, different fault: this value came back from the provider."""
        with pytest.raises(AuthenticationException) as exc:
            oidc_utils.normalize_issuer(issuer, from_configuration=False)
        assert exc.value.error_message == "OIDC_OAUTH_PROVIDER_ERROR"
