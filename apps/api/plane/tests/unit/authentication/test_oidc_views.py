# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Guards on the OIDC callback endpoints.

Both callbacks reject the request before any provider or database work happens, so
these run on a bare RequestFactory. The nonce check matters as much as the state
check: state proves the redirect belongs to this browser, nonce proves the ID token
does. Losing either one silently would leave the token unbound to the session.
"""

from unittest.mock import MagicMock, patch

import pytest
from django.test import RequestFactory

from plane.authentication.views.app.oidc import (
    NONCE_SESSION_KEY,
    STATE_SESSION_KEY,
    OIDCCallbackEndpoint,
)
from plane.authentication.views.space.oidc import (
    NONCE_SESSION_KEY as SPACE_NONCE_SESSION_KEY,
)
from plane.authentication.views.space.oidc import (
    STATE_SESSION_KEY as SPACE_STATE_SESSION_KEY,
)
from plane.authentication.views.space.oidc import (
    OIDCCallbackSpaceEndpoint,
)
from plane.authentication.views.space import oidc as space_oidc

# 5114 = OIDC_OAUTH_PROVIDER_ERROR, the code both callbacks refuse with.
REFUSAL_CODE = "5114"


@pytest.fixture(autouse=True)
def base_urls(settings):
    """base_host() builds the refusal redirect from these; unset they yield None."""
    settings.WEB_URL = "https://plane.example.com"
    settings.APP_BASE_URL = "https://plane.example.com"
    settings.SPACE_BASE_URL = "https://plane.example.com"


def make_request(session, query):
    request = RequestFactory().get("/auth/oidc/callback/", query)
    request.session = dict(session)
    return request


def refused(response):
    """A refusal is a redirect back to the sign-in page carrying the error code."""
    return response.status_code == 302 and f"error_code={REFUSAL_CODE}" in response.url


@pytest.mark.unit
@pytest.mark.parametrize(
    ("view", "state_key", "nonce_key"),
    [
        (OIDCCallbackEndpoint, STATE_SESSION_KEY, NONCE_SESSION_KEY),
        (OIDCCallbackSpaceEndpoint, SPACE_STATE_SESSION_KEY, SPACE_NONCE_SESSION_KEY),
    ],
    ids=["app", "spaces"],
)
class TestCallbackGuards:
    def test_missing_nonce_is_refused(self, view, state_key, nonce_key):
        """State alone is not enough: without the nonce the ID token would be
        validated with no session binding, so the login is refused instead."""
        request = make_request({state_key: "s1"}, {"code": "c", "state": "s1"})
        assert refused(view().get(request))

    def test_mismatched_state_is_refused(self, view, state_key, nonce_key):
        request = make_request({state_key: "s1", nonce_key: "n1"}, {"code": "c", "state": "other"})
        assert refused(view().get(request))

    def test_absent_state_in_session_is_refused(self, view, state_key, nonce_key):
        request = make_request({}, {"code": "c", "state": "s1"})
        assert refused(view().get(request))

    def test_missing_code_is_refused(self, view, state_key, nonce_key):
        request = make_request({state_key: "s1", nonce_key: "n1"}, {"state": "s1"})
        assert refused(view().get(request))

    def test_state_and_nonce_are_single_use(self, view, state_key, nonce_key):
        """Both are popped, so a replayed callback finds nothing left to match.

        The state check passes here and the request is refused for the missing code
        instead, which keeps the test out of the provider while still proving the pop
        happens on a request that got past state validation.
        """
        session = {state_key: "s1", nonce_key: "n1"}
        request = RequestFactory().get("/auth/oidc/callback/", {"state": "s1"})
        request.session = session

        assert refused(view().get(request))
        assert state_key not in session
        assert nonce_key not in session

        # Replaying the same callback now fails the state check outright.
        replay = make_request(session, {"code": "c", "state": "s1"})
        assert refused(view().get(replay))


@pytest.mark.unit
class TestSpacesLandingUrl:
    """Where a successful Spaces login comes to rest.

    SPACE_BASE_PATH contributes a trailing slash that the callback used to strip
    unconditionally, sending the browser to /spaces. The Spaces app declares a base URL of
    /spaces/ and 404s on the bare form, so the slash has to survive when there is no
    next_path to append.
    """

    def _run(self, session_next_path=None):
        session = {SPACE_STATE_SESSION_KEY: "s1", SPACE_NONCE_SESSION_KEY: "n1"}
        if session_next_path:
            session["next_path"] = session_next_path
        request = RequestFactory().get("/auth/spaces/oidc/callback/", {"code": "c", "state": "s1"})
        request.session = session

        provider = MagicMock()
        provider.authenticate.return_value = MagicMock()
        with (
            patch.object(space_oidc, "OIDCProvider", return_value=provider),
            patch.object(space_oidc, "user_login"),
        ):
            return OIDCCallbackSpaceEndpoint().get(request)

    def test_lands_on_the_spaces_base_path_with_its_trailing_slash(self):
        assert self._run().url == "https://plane.example.com/spaces/"

    def test_next_path_is_appended_without_doubling_the_slash(self):
        assert self._run(session_next_path="/foo").url == "https://plane.example.com/spaces/foo"
