# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

# Python imports
import base64
import os
from datetime import datetime, timedelta
from urllib.parse import urlencode

import pytz

# Module imports
from plane.authentication.adapter.oauth import OauthAdapter
from plane.authentication.adapter.error import (
    AUTHENTICATION_ERROR_CODES,
    AuthenticationException,
)
from plane.authentication.utils.oidc import (
    get_discovery_document,
    normalize_issuer,
    validate_id_token,
)
from plane.license.utils.instance_value import get_configuration_value


class OIDCProvider(OauthAdapter):
    """Generic OpenID Connect provider.

    Unlike the other providers in this package, every endpoint is discovered from
    the admin-configured issuer rather than hardcoded, so one implementation serves
    any compliant IdP (Okta, Entra ID, Keycloak, Auth0, Authentik, Google).

    Identity comes from the ID token, which is verified in set_token_data() before
    any claim is read. The userinfo endpoint is consulted only to fill in profile
    fields the ID token omitted, and never to establish who the user is.
    """

    provider = "oidc"
    scope = "openid email profile"

    def __init__(self, request, code=None, state=None, nonce=None, callback=None, is_space=False):
        (
            OIDC_ISSUER_URL,
            OIDC_CLIENT_ID,
            OIDC_CLIENT_SECRET,
        ) = get_configuration_value(
            [
                {"key": "OIDC_ISSUER_URL", "default": os.environ.get("OIDC_ISSUER_URL")},
                {"key": "OIDC_CLIENT_ID", "default": os.environ.get("OIDC_CLIENT_ID")},
                {"key": "OIDC_CLIENT_SECRET", "default": os.environ.get("OIDC_CLIENT_SECRET")},
            ]
        )

        if not (OIDC_ISSUER_URL and OIDC_CLIENT_ID and OIDC_CLIENT_SECRET):
            raise AuthenticationException(
                error_code=AUTHENTICATION_ERROR_CODES["OIDC_NOT_CONFIGURED"],
                error_message="OIDC_NOT_CONFIGURED",
            )

        self.issuer = normalize_issuer(OIDC_ISSUER_URL)
        self.nonce = nonce
        # Populated by set_token_data() once the ID token has been verified.
        self.id_token_claims = None

        # Resolve the provider's endpoints. Cached, so this is a network call only
        # on the first login after the cache expires.
        self.discovery_document = get_discovery_document(self.issuer)

        authorization_endpoint = self.discovery_document["authorization_endpoint"]
        token_url = self.discovery_document["token_endpoint"]
        # userinfo_endpoint is optional in the spec; profile fallback is skipped without it.
        userinfo_url = self.discovery_document.get("userinfo_endpoint")

        # The /app and /spaces flows have separate callback endpoints and separate
        # session keys, so the IdP must be sent back to whichever one started this.
        # OAuth also requires the redirect_uri on the token exchange to match the one
        # on the authorization request, so the callback leg builds it the same way.
        callback_path = "/auth/spaces/oidc/callback/" if is_space else "/auth/oidc/callback/"
        redirect_uri = f"""{"https" if request.is_secure() else "http"}://{request.get_host()}{callback_path}"""

        url_params = {
            "client_id": OIDC_CLIENT_ID,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": self.scope,
            "state": state,
        }
        # The nonce is only meaningful on the authorization request; on the callback
        # leg it is the value we compare the returned token against instead.
        if nonce and state:
            url_params["nonce"] = nonce

        auth_url = f"{authorization_endpoint}?{urlencode(url_params)}"

        super().__init__(
            request,
            self.provider,
            OIDC_CLIENT_ID,
            self.scope,
            redirect_uri,
            auth_url,
            token_url,
            userinfo_url,
            OIDC_CLIENT_SECRET,
            code,
            callback=callback,
        )

    def _token_request_auth(self):
        """Return (extra_form_fields, headers) for authenticating to the token endpoint.

        Providers advertise which client authentication methods they accept. Sending
        the secret in the form body (client_secret_post) matches what the other
        providers here do, but some IdPs only accept HTTP Basic (client_secret_basic),
        so honour whatever the discovery document says.
        """
        supported = self.discovery_document.get("token_endpoint_auth_methods_supported") or []

        # OIDC Discovery 1.0 §3 makes this field OPTIONAL and states that when it is
        # omitted "the default is client_secret_basic". So an absent list means basic,
        # not a free choice: a compliant provider that only accepts the default and
        # does not publish the list would reject a form-body secret outright.
        #
        # When the list *is* published, prefer client_secret_post where offered, which
        # is what the other providers in this package send.
        use_basic = "client_secret_basic" in supported if supported else True
        if supported and "client_secret_post" in supported:
            use_basic = False

        if use_basic:
            credentials = f"{self.client_id}:{self.client_secret}".encode("utf-8")
            encoded = base64.b64encode(credentials).decode("ascii")
            return {}, {"Accept": "application/json", "Authorization": f"Basic {encoded}"}

        return (
            {"client_id": self.client_id, "client_secret": self.client_secret},
            {"Accept": "application/json"},
        )

    def set_token_data(self):
        auth_fields, headers = self._token_request_auth()
        data = {
            "grant_type": "authorization_code",
            "code": self.code,
            "redirect_uri": self.redirect_uri,
            **auth_fields,
        }
        token_response = self.get_user_token(data=data, headers=headers)

        # Verify the ID token before anything downstream reads a claim from it.
        # This is the step that makes the whole flow trustworthy, so it happens
        # here rather than in set_user_data().
        self.id_token_claims = validate_id_token(
            id_token=token_response.get("id_token"),
            discovery_document=self.discovery_document,
            client_id=self.client_id,
            nonce=self.nonce,
        )

        # expires_in is a duration in seconds from now (RFC 6749 §5.1), unlike the
        # absolute timestamps some of the other providers here return.
        expires_in = token_response.get("expires_in")
        access_token_expired_at = datetime.now(tz=pytz.utc) + timedelta(seconds=int(expires_in)) if expires_in else None
        refresh_expires_in = token_response.get("refresh_expires_in")
        refresh_token_expired_at = (
            datetime.now(tz=pytz.utc) + timedelta(seconds=int(refresh_expires_in)) if refresh_expires_in else None
        )

        super().set_token_data(
            {
                "access_token": token_response.get("access_token"),
                "refresh_token": token_response.get("refresh_token", None),
                "access_token_expired_at": access_token_expired_at,
                "refresh_token_expired_at": refresh_token_expired_at,
                "id_token": token_response.get("id_token", ""),
            }
        )

    def _get_profile_claims(self):
        """Merge ID token claims with userinfo, preferring the signed ID token."""
        claims = dict(self.id_token_claims)

        # Consult userinfo only when the ID token is genuinely short of something we
        # need: an email to identify the account by, the verification status we gate
        # on, or any name to display. Plenty of IdPs put all of it in the ID token,
        # and fetching userinfo regardless would add a round trip to every login.
        #
        # email_verified has to be part of this test, not just email. Providers vary
        # in which claims reach the ID token versus userinfo -- Authentik, for one,
        # only puts scope-mapped claims in the ID token when the provider enables it
        # -- so treating a missing email_verified as "nothing more to fetch" rejects
        # logins over a claim the userinfo endpoint would have supplied.
        has_email = claims.get("email") is not None
        has_verification = claims.get("email_verified") is not None
        has_name = any(claims.get(field) is not None for field in ("given_name", "family_name", "name"))
        if not self.userinfo_url or (has_email and has_verification and has_name):
            return claims

        userinfo = self.get_user_response()

        # The userinfo response is unsigned, so it is merged only once it proves it
        # describes the same subject as the verified ID token (OIDC Core 1.0 5.3.2).
        # A response that does not is discarded rather than trusted: otherwise a
        # provider bug or a swapped response could graft another user's profile, or
        # another user's email, onto this session. Discarding rather than failing
        # keeps a quirky userinfo endpoint from locking out logins that the ID token
        # alone could satisfy; if that leaves no email at all, the adapter's own
        # email validation rejects the login further down.
        if userinfo.get("sub") != claims.get("sub"):
            self.logger.warning("OIDC: discarding userinfo response whose sub does not match the id_token")
            return claims

        for field in ("email", "email_verified", "given_name", "family_name", "name", "picture"):
            if claims.get(field) is None and userinfo.get(field) is not None:
                claims[field] = userinfo[field]

        return claims

    def set_user_data(self):
        claims = self._get_profile_claims()

        # Reject unverified emails. An IdP that has not verified the address cannot
        # vouch for it, and Plane matches accounts by email — so accepting one lets
        # whoever controls that unverified address take over an existing account
        # (GHSA-7j95-vh8g-f365). Fail closed: an absent claim counts as unverified.
        #
        # Not every IdP emits email_verified (Entra ID commonly omits it), so an
        # admin whose provider verifies addresses out of band can opt out with
        # OIDC_ALLOW_UNVERIFIED_EMAIL=1. Doing so means trusting that IdP to only
        # ever assert addresses it controls.
        (OIDC_ALLOW_UNVERIFIED_EMAIL,) = get_configuration_value(
            [
                {
                    "key": "OIDC_ALLOW_UNVERIFIED_EMAIL",
                    "default": os.environ.get("OIDC_ALLOW_UNVERIFIED_EMAIL", "0"),
                }
            ]
        )
        if OIDC_ALLOW_UNVERIFIED_EMAIL != "1" and claims.get("email_verified") is not True:
            raise AuthenticationException(
                error_code=AUTHENTICATION_ERROR_CODES["OAUTH_PROVIDER_UNVERIFIED_EMAIL"],
                error_message="OAUTH_PROVIDER_UNVERIFIED_EMAIL",
            )

        # Some IdPs send only a full `name`; split it so first/last are populated.
        first_name = claims.get("given_name")
        last_name = claims.get("family_name")
        if not first_name and claims.get("name"):
            first_name, _, last_name_fallback = str(claims["name"]).partition(" ")
            last_name = last_name or last_name_fallback

        super().set_user_data(
            {
                "email": claims.get("email"),
                "user": {
                    # `sub` is the only claim guaranteed stable for the user at this
                    # issuer; email can be reassigned, so it must not key the account.
                    "provider_id": claims.get("sub"),
                    "email": claims.get("email"),
                    "avatar": claims.get("picture"),
                    "first_name": first_name,
                    "last_name": last_name,
                    "is_password_autoset": True,
                },
            }
        )
