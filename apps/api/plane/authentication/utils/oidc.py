# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""OpenID Connect discovery and ID token validation.

The existing OAuth providers (google, github, gitlab, gitea) obtain identity by
calling a provider-specific userinfo endpoint with the access token. OIDC instead
carries identity in a signed ID token, so the trust anchor is the token signature
rather than the transport. Everything in this module exists to make that signature
check correct: getting the right keys, and rejecting every token that does not
prove it came from the configured issuer for this client.
"""

# Python imports
import hmac
import logging
from urllib.parse import urlparse

# Third party imports
import jwt
import requests
from jwt import PyJWKClient

# Django imports
from django.core.cache import cache

# Module imports
from plane.authentication.adapter.error import (
    AUTHENTICATION_ERROR_CODES,
    AuthenticationException,
)

logger = logging.getLogger("plane.authentication")

# How long a provider's discovery document is reused before being re-fetched.
DISCOVERY_CACHE_TTL = 60 * 60  # 1 hour
DISCOVERY_CACHE_PREFIX = "oidc:discovery:"

# Network timeout for discovery and JWKS fetches, in seconds.
NETWORK_TIMEOUT = 10

# Signing algorithms accepted for an ID token.
#
# Asymmetric only, and this is a security control rather than a preference. If a
# symmetric algorithm (HS256) were permitted, an attacker could forge a token by
# signing it with the issuer's *public* key as the HMAC secret — the public key
# is published in the JWKS, so it is not a secret at all. PyJWT would then verify
# that forgery successfully because the key material matches. "none" is excluded
# for the same class of reason: it asserts identity with no proof whatsoever.
ALLOWED_SIGNING_ALGORITHMS = frozenset(
    {"RS256", "RS384", "RS512", "ES256", "ES384", "ES512", "PS256", "PS384", "PS512"}
)

# Endpoints a discovery document must advertise for the login flow to work.
REQUIRED_DISCOVERY_FIELDS = ("issuer", "authorization_endpoint", "token_endpoint", "jwks_uri")

# Every endpoint this module actually calls. userinfo_endpoint is optional in the
# spec, so it is checked only when present.
DISCOVERY_ENDPOINT_FIELDS = ("authorization_endpoint", "token_endpoint", "jwks_uri", "userinfo_endpoint")

# Tolerated clock skew between this instance and the identity provider, in seconds.
LEEWAY = 60


def _provider_error(message):
    """Raise the generic OIDC provider error, logging the specific cause server-side.

    The detail is deliberately not surfaced to the caller: the error travels back to
    the browser as a query parameter on the sign-in page.

    Callers must pass a constant description and never interpolate configuration
    values. Issuer, client id and client secret all arrive from the same
    get_configuration_value() call, so letting any of them reach this log makes the
    secret one edit away from being written to disk in clear text. An instance has a
    single configured issuer, so a constant message is still unambiguous.
    """
    logger.warning("OIDC: %s", message)
    raise AuthenticationException(
        error_code=AUTHENTICATION_ERROR_CODES["OIDC_OAUTH_PROVIDER_ERROR"],
        error_message="OIDC_OAUTH_PROVIDER_ERROR",
    )


def normalize_issuer(issuer, *, from_configuration=True):
    """Return the issuer without a trailing slash, validating its form.

    The issuer identifier is compared byte-for-byte against the `iss` claim later,
    so it has to be normalized once, here, and used consistently everywhere.

    Two kinds of caller reach this, and they differ in whose mistake a bad value is.
    The configured issuer is the administrator's to fix, so it fails as
    OIDC_NOT_CONFIGURED and the sign-in page tells the user to contact their
    administrator. The issuer echoed back inside a discovery document is the
    provider's, so that path fails as the generic provider error and says to try
    again. Passing both through one error code sent an admin who typed `http://`
    chasing a transient fault that would never clear.
    """

    def reject(reason):
        if from_configuration:
            # Reason strings here are constants: the issuer arrives from the same
            # configuration that holds OIDC_CLIENT_SECRET, so none of it is logged.
            logger.warning("OIDC: %s", reason)
            raise AuthenticationException(
                error_code=AUTHENTICATION_ERROR_CODES["OIDC_NOT_CONFIGURED"],
                error_message="OIDC_NOT_CONFIGURED",
            )
        _provider_error(reason)

    if not issuer:
        reject("issuer is empty")

    issuer = str(issuer).strip().rstrip("/")
    parsed = urlparse(issuer)

    # OIDC Discovery requires the issuer to be an https URL with no query or
    # fragment. Enforcing it here means a misconfigured instance fails at the
    # admin panel rather than silently downgrading every login to plaintext.
    if parsed.scheme != "https" or not parsed.netloc or parsed.query or parsed.fragment:
        reject("issuer is not a valid https URL")

    return issuer


def get_discovery_document(issuer):
    """Fetch and cache the provider's OpenID configuration.

    Returns the parsed document. Raises AuthenticationException if the provider is
    unreachable, malformed, or asserts an issuer other than the configured one.
    """
    issuer = normalize_issuer(issuer)
    cache_key = f"{DISCOVERY_CACHE_PREFIX}{issuer}"

    document = cache.get(cache_key)
    if document:
        return document

    discovery_url = f"{issuer}/.well-known/openid-configuration"
    try:
        response = requests.get(discovery_url, timeout=NETWORK_TIMEOUT)
        response.raise_for_status()
        document = response.json()
    except requests.RequestException:
        _provider_error("could not fetch the provider's discovery document")
    except ValueError:
        _provider_error("discovery document is not valid JSON")

    if not isinstance(document, dict):
        _provider_error("discovery document is not a JSON object")

    missing = [field for field in REQUIRED_DISCOVERY_FIELDS if not document.get(field)]
    if missing:
        # The field names are not interpolated: anything derived from the document
        # carries taint from the configured issuer, and that config also holds the
        # client secret. REQUIRED_DISCOVERY_FIELDS lists what a document must carry.
        _provider_error("discovery document is missing one or more required fields")

    # Validating the issuer's scheme is not enough: the endpoints inside the document
    # are separate URLs and may point anywhere. OIDC Discovery 1.0 requires https for
    # all of them, and the consequences here are concrete rather than theoretical --
    # token_endpoint receives the authorization code together with the client secret,
    # and jwks_uri supplies the keys every ID token signature is checked against. A
    # document advertising http:// for either would put the secret on the wire in
    # clear text, or let anyone on the path serve their own signing keys.
    insecure = [
        field
        for field in DISCOVERY_ENDPOINT_FIELDS
        if document.get(field) and urlparse(str(document[field])).scheme != "https"
    ]
    if insecure:
        _provider_error("discovery document advertises one or more non-https endpoints")

    # The document must claim the issuer we asked about. Without this check a
    # provider could hand back another issuer's endpoints, and tokens minted by
    # that third party would then satisfy the `iss` check below (OIDC Discovery
    # 1.0 §4.3 makes this comparison mandatory for exactly that reason).
    if normalize_issuer(document.get("issuer"), from_configuration=False) != issuer:
        _provider_error("discovery document issuer does not match the configured issuer")

    cache.set(cache_key, document, DISCOVERY_CACHE_TTL)
    return document


def get_signing_algorithms(discovery_document):
    """Return the algorithms to accept: the provider's advertised set, filtered to the allowlist."""
    advertised = discovery_document.get("id_token_signing_alg_values_supported") or []
    algorithms = [alg for alg in advertised if alg in ALLOWED_SIGNING_ALGORITHMS]

    if not algorithms:
        # Either the provider advertises nothing usable, or it only offers
        # symmetric/none signing. Both are refusals rather than fallbacks: there is
        # no safe default to substitute here.
        # The advertised list is deliberately not logged, for the reason above. Check
        # id_token_signing_alg_values_supported in the provider's own metadata.
        _provider_error("provider advertises no supported ID token signing algorithm")

    return algorithms


# PyJWKClient instances, keyed by jwks_uri. Each one holds its own key-set cache
# with a TTL, so keeping them alive is what makes that cache effective. The set of
# issuers on an instance is bounded by configuration, so this cannot grow unbounded.
_jwk_clients = {}


def _get_jwk_client(jwks_uri):
    """Return a cached PyJWKClient for the given JWKS endpoint."""
    client = _jwk_clients.get(jwks_uri)
    if client is None:
        client = PyJWKClient(jwks_uri, cache_jwk_set=True, lifespan=DISCOVERY_CACHE_TTL)
        _jwk_clients[jwks_uri] = client
    return client


def validate_id_token(id_token, discovery_document, client_id, nonce=None):
    """Verify an ID token's signature and claims, returning its payload.

    Every parameter is part of the security boundary:
      * the signature is checked against the issuer's published JWKS,
      * `iss` must equal the configured issuer,
      * `aud` must contain this instance's client_id,
      * `exp`/`iat` must be current,
      * `nonce` must match the value this instance put in the session.
    """
    if not id_token:
        logger.warning("OIDC: token response contained no id_token")
        raise AuthenticationException(
            error_code=AUTHENTICATION_ERROR_CODES["OIDC_INVALID_ID_TOKEN"],
            error_message="OIDC_INVALID_ID_TOKEN",
        )

    issuer = discovery_document["issuer"]
    algorithms = get_signing_algorithms(discovery_document)

    try:
        # PyJWKClient reads the token header to select the matching key by `kid`.
        # Its key-set cache lives on the instance, so the client itself is reused
        # across logins — a fresh client per request would refetch the JWKS every
        # single time and make the cache pointless.
        jwk_client = _get_jwk_client(discovery_document["jwks_uri"])
        signing_key = jwk_client.get_signing_key_from_jwt(id_token)
    except (jwt.PyJWTError, requests.RequestException) as e:
        logger.warning("OIDC: could not resolve signing key for id_token: %s", e)
        raise AuthenticationException(
            error_code=AUTHENTICATION_ERROR_CODES["OIDC_INVALID_ID_TOKEN"],
            error_message="OIDC_INVALID_ID_TOKEN",
        )

    try:
        claims = jwt.decode(
            id_token,
            signing_key.key,
            algorithms=algorithms,
            audience=client_id,
            issuer=issuer,
            leeway=LEEWAY,
            options={
                "verify_signature": True,
                "verify_exp": True,
                "verify_iat": True,
                "verify_aud": True,
                "verify_iss": True,
                "require": ["iss", "sub", "aud", "exp", "iat"],
            },
        )
    except jwt.PyJWTError as e:
        # Covers expired, wrong audience, wrong issuer, bad signature and missing
        # required claims. The specific reason is logged but never returned.
        logger.warning("OIDC: id_token rejected: %s", e)
        raise AuthenticationException(
            error_code=AUTHENTICATION_ERROR_CODES["OIDC_INVALID_ID_TOKEN"],
            error_message="OIDC_INVALID_ID_TOKEN",
        )

    # When the token is issued to more than one audience, OIDC Core §3.1.3.7 requires
    # an `azp` claim naming the party the token was actually issued to. PyJWT's
    # audience check passes as long as our client_id appears anywhere in the list,
    # so without this a token minted for a different client at the same issuer would
    # be accepted here.
    audience = claims.get("aud")
    if isinstance(audience, (list, tuple)) and len(audience) > 1:
        if claims.get("azp") != client_id:
            # Neither value is logged: client_id comes from instance configuration.
            logger.warning("OIDC: id_token lists multiple audiences and azp does not name this client")
            raise AuthenticationException(
                error_code=AUTHENTICATION_ERROR_CODES["OIDC_INVALID_ID_TOKEN"],
                error_message="OIDC_INVALID_ID_TOKEN",
            )

    # The nonce binds this token to the browser session that started the flow, which
    # is what stops a token replayed from another session being accepted here.
    # Compared in constant time, and a missing claim fails closed.
    if nonce is not None:
        token_nonce = claims.get("nonce")
        if not token_nonce or not hmac.compare_digest(str(token_nonce), str(nonce)):
            logger.warning("OIDC: id_token nonce mismatch")
            raise AuthenticationException(
                error_code=AUTHENTICATION_ERROR_CODES["OIDC_INVALID_ID_TOKEN"],
                error_message="OIDC_INVALID_ID_TOKEN",
            )

    return claims
