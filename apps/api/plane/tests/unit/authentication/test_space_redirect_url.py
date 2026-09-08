# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Post-login redirect construction for the /spaces app.

`base_host(is_space=True)` ends with SPACE_BASE_PATH's trailing slash, and the two naive
ways of appending a next_path to it are each wrong in a different direction. Both were
present in the tree: most space views stripped the slash unconditionally and so landed on
/spaces, which the Spaces app rejects; the Gitea view never stripped it and so produced a
doubled separator whenever a next_path existed.
"""

import pytest
from django.test import RequestFactory

from plane.authentication.utils.host import space_redirect_url


@pytest.fixture(autouse=True)
def base_urls(settings):
    settings.WEB_URL = "https://plane.example.com"
    settings.APP_BASE_URL = "https://plane.example.com"
    settings.SPACE_BASE_URL = "https://plane.example.com"


@pytest.fixture
def request_obj():
    return RequestFactory().get("/auth/spaces/oidc/callback/")


@pytest.mark.unit
class TestSpaceRedirectUrl:
    @pytest.mark.parametrize("next_path", [None, "", "   "], ids=["none", "empty", "blank"])
    def test_keeps_the_trailing_slash_when_there_is_nothing_to_append(self, request_obj, next_path):
        """A bare /spaces is refused by the app, whose base URL is /spaces/."""
        assert space_redirect_url(request_obj, next_path) == "https://plane.example.com/spaces/"

    def test_appends_a_next_path_without_doubling_the_separator(self, request_obj):
        assert space_redirect_url(request_obj, "/issues") == "https://plane.example.com/spaces/issues"

    def test_appends_a_nested_next_path(self, request_obj):
        assert space_redirect_url(request_obj, "/issues/abc-123") == "https://plane.example.com/spaces/issues/abc-123"

    @pytest.mark.parametrize(
        "hostile",
        [
            "https://evil.example.com/steal",
            "//evil.example.com/steal",
            "http://evil.example.com",
        ],
    )
    def test_absolute_urls_cannot_redirect_off_site(self, request_obj, hostile):
        """validate_next_path keeps only the path component, so an attacker-supplied
        next_path cannot move the redirect to another origin."""
        url = space_redirect_url(request_obj, hostile)
        assert url.startswith("https://plane.example.com/spaces")
        assert "evil.example.com" not in url

    def test_a_relative_next_path_is_discarded(self, request_obj):
        """validate_next_path requires a leading slash; anything else is dropped."""
        assert space_redirect_url(request_obj, "issues") == "https://plane.example.com/spaces/"
