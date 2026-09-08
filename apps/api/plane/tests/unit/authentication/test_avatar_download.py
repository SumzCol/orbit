# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Avatar download guard on the shared OAuth adapter.

Providers are free to return something other than a fetchable URL. Authentik generates a
`data:image/svg+xml;base64,...` avatar for users with no uploaded picture, and passing that
to the SSRF-safe fetcher raises ValueError("Invalid URL scheme..."), which the surrounding
`except Exception` records via log_exception — a full stack trace on every single sign-in.
The guard returns early instead, so the caller stores the value as-is and the avatar still
renders.
"""

from unittest.mock import MagicMock, patch

import pytest

from plane.authentication.adapter.base import Adapter

DATA_URI = "data:image/svg+xml;base64,PHN2ZyB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciPjwvc3ZnPg=="


@pytest.fixture
def adapter():
    return Adapter(request=MagicMock(), provider="oidc")


@pytest.mark.unit
class TestDownloadAndUploadAvatar:
    @pytest.mark.parametrize(
        "avatar_url",
        [DATA_URI, "ftp://example.com/a.png", "file:///etc/passwd", "javascript:alert(1)"],
        ids=["data-uri", "ftp", "file", "javascript"],
    )
    def test_non_http_urls_are_skipped_without_fetching_or_logging(self, adapter, avatar_url):
        with (
            patch("plane.authentication.adapter.base.pinned_fetch_following_redirects") as fetch,
            patch("plane.authentication.adapter.base.log_exception") as log_exception,
        ):
            assert adapter.download_and_upload_avatar(avatar_url, user=MagicMock()) is None

        fetch.assert_not_called()
        # The point of the guard: no stack trace per sign-in.
        log_exception.assert_not_called()

    @pytest.mark.parametrize("avatar_url", [None, ""], ids=["none", "empty"])
    def test_absent_avatar_is_skipped(self, adapter, avatar_url):
        with patch("plane.authentication.adapter.base.pinned_fetch_following_redirects") as fetch:
            assert adapter.download_and_upload_avatar(avatar_url, user=MagicMock()) is None
        fetch.assert_not_called()

    @pytest.mark.parametrize(
        "avatar_url",
        ["https://example.com/a.png", "http://example.com/a.png", "HTTPS://EXAMPLE.COM/a.png"],
        ids=["https", "http", "uppercase-scheme"],
    )
    def test_http_urls_still_reach_the_fetcher(self, adapter, avatar_url):
        """The guard must not change behaviour for the providers that return real URLs."""
        with patch("plane.authentication.adapter.base.pinned_fetch_following_redirects") as fetch:
            fetch.side_effect = RuntimeError("stop here")
            with patch("plane.authentication.adapter.base.log_exception"):
                adapter.download_and_upload_avatar(avatar_url, user=MagicMock())
        fetch.assert_called_once()
