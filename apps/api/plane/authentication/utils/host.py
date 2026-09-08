# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

# Django imports
from django.conf import settings
from django.http import HttpRequest

# Third party imports
from rest_framework.request import Request

# Module imports
from plane.utils.ip_address import get_client_ip
from plane.utils.path_validator import validate_next_path


def base_host(
    request: Request | HttpRequest,
    is_admin: bool = False,
    is_space: bool = False,
    is_app: bool = False,
) -> str:
    """Utility function to return host / origin from the request"""
    # Calculate the base origin from request
    base_origin = settings.WEB_URL or settings.APP_BASE_URL

    # Admin redirection
    if is_admin:
        admin_base_path = getattr(settings, "ADMIN_BASE_PATH", None)
        if not isinstance(admin_base_path, str):
            admin_base_path = "/god-mode/"
        if not admin_base_path.startswith("/"):
            admin_base_path = "/" + admin_base_path
        if not admin_base_path.endswith("/"):
            admin_base_path += "/"

        if settings.ADMIN_BASE_URL:
            return settings.ADMIN_BASE_URL + admin_base_path
        else:
            return base_origin + admin_base_path

    # Space redirection
    if is_space:
        space_base_path = getattr(settings, "SPACE_BASE_PATH", None)
        if not isinstance(space_base_path, str):
            space_base_path = "/spaces/"
        if not space_base_path.startswith("/"):
            space_base_path = "/" + space_base_path
        if not space_base_path.endswith("/"):
            space_base_path += "/"

        if settings.SPACE_BASE_URL:
            return settings.SPACE_BASE_URL + space_base_path
        else:
            return base_origin + space_base_path

    # App Redirection
    if is_app:
        if settings.APP_BASE_URL:
            return settings.APP_BASE_URL
        else:
            return base_origin

    return base_origin


def user_ip(request: Request | HttpRequest) -> str:
    return get_client_ip(request=request)


def space_redirect_url(request: Request | HttpRequest, next_path: str | None) -> str:
    """Build the post-login redirect for the /spaces app.

    base_host(is_space=True) already ends with SPACE_BASE_PATH's trailing slash, which
    makes both naive forms wrong:

      * stripping it and appending an empty next_path lands on /spaces, and the Spaces
        app refuses that -- it declares a public base URL of /spaces/ and answers with
        "did you mean to visit /spaces/ instead?";
      * appending a next_path that also starts with "/" doubles the separator.

    So the slash is kept when there is nothing to append and dropped when there is.
    next_path is validated here, so callers do not need to pre-validate it.
    """
    base_url = base_host(request=request, is_space=True)
    # Coerced rather than passed straight through: validate_next_path is annotated
    # `str` and only guards non-strings at runtime, so handing it None would make this
    # helper's own `str | None` signature dishonest. "" and None validate identically.
    validated_path = validate_next_path(next_path or "")

    if not validated_path:
        return base_url

    return f"{base_url.rstrip('/')}{validated_path}"
