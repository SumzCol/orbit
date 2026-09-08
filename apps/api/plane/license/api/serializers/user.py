# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

from rest_framework import serializers

from .base import BaseSerializer
from plane.db.models import User


class UserLiteSerializer(BaseSerializer):
    class Meta:
        model = User
        fields = ["id", "email", "first_name", "last_name"]


class InstanceUserSerializer(BaseSerializer):
    """A user as the God Mode user list presents them.

    `instance_admin_id` is annotated by the endpoint rather than derived here: demoting
    an admin addresses the InstanceAdmin row by its own pk, not the user's, so without
    it the interface has no way to build that call. It is null for a regular member,
    which is also what distinguishes the two account types.

    `is_deactivated` reads the same pair the sign-in guard does. `is_active` alone is
    ambiguous -- a freshly provisioned account has it false while having never been
    deactivated -- so the two fields together are what tell an administrator whether
    this person can currently sign in.

    `is_password_autoset` is here because God Mode accepts only email and password:
    InstanceAdminSignInEndpoint calls check_password and has no OAuth branch. An account
    provisioned through OIDC or any other provider was given a random password it can
    never know, so granting it admin access is not by itself enough to let it in. The
    interface warns on this rather than hiding the action, since the person can set a
    password from their profile at any time.
    """

    instance_admin_id = serializers.UUIDField(read_only=True, default=None)
    is_instance_admin = serializers.SerializerMethodField()
    is_deactivated = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = [
            "id",
            "email",
            "first_name",
            "last_name",
            "display_name",
            "avatar_url",
            "date_joined",
            "last_login_time",
            "last_login_medium",
            "is_active",
            "is_deactivated",
            "is_password_autoset",
            "is_instance_admin",
            "instance_admin_id",
        ]
        read_only_fields = fields

    def get_is_instance_admin(self, obj) -> bool:
        return getattr(obj, "instance_admin_id", None) is not None

    def get_is_deactivated(self, obj) -> bool:
        return not obj.is_active and obj.last_logout_time is not None
