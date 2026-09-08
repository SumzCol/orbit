# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

# Django imports
from django.db.models import OuterRef, Q, Subquery

# Module imports
from plane.app.views.base import BaseAPIView
from plane.db.models import User
from plane.license.api.permissions import InstanceAdminPermission
from plane.license.api.serializers import InstanceUserSerializer
from plane.license.models import InstanceAdmin


class InstanceUserEndpoint(BaseAPIView):
    """Every person on the instance, for the God Mode user list."""

    model = User
    serializer_class = InstanceUserSerializer
    permission_classes = [InstanceAdminPermission]

    def get(self, request):
        # Bots (WORKSPACE_SEED and friends) are internal identities that act only
        # through API tokens. They are not administrable people, they cannot sign in,
        # and listing them would offer actions that mean nothing for them.
        users = User.objects.filter(is_bot=False).annotate(
            instance_admin_id=Subquery(InstanceAdmin.objects.filter(user_id=OuterRef("id")).values("id")[:1])
        )

        search = request.query_params.get("search", None)
        if search:
            users = users.filter(
                Q(email__icontains=search)
                | Q(display_name__icontains=search)
                | Q(first_name__icontains=search)
                | Q(last_name__icontains=search)
            )

        return self.paginate(
            request=request,
            queryset=users.order_by("-date_joined"),
            on_results=lambda results: InstanceUserSerializer(results, many=True).data,
        )
