# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

# Django imports
from django.db.models import OuterRef, Q, Subquery

# Third party imports
from rest_framework import status
from rest_framework.response import Response

# Module imports
from plane.app.views.base import BaseAPIView
from plane.db.models import User
from plane.license.api.permissions import InstanceAdminPermission
from plane.license.api.serializers import InstanceUserSerializer
from plane.license.models import InstanceAdmin
from plane.utils.user_deactivation import activate_user, deactivate_user


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


class InstanceUserDeactivateEndpoint(BaseAPIView):
    """Suspend an account from God Mode."""

    permission_classes = [InstanceAdminPermission]

    def post(self, request, user_id):
        target = User.objects.filter(pk=user_id, is_bot=False).first()
        if target is None:
            return Response({"error": "User not found."}, status=status.HTTP_404_NOT_FOUND)

        # An administrator suspending themselves would lose God Mode along with it,
        # and could not undo it from the interface that did it. The instance-admin
        # rule below already covers this, but only as a side effect -- refusing it by
        # name gives the honest reason instead of "remove admin access first".
        if target.id == request.user.id:
            return Response(
                {"error": "You cannot deactivate your own account."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        error = deactivate_user(target=target, actor=request.user, request=request)
        if error:
            return Response({"error": error}, status=status.HTTP_400_BAD_REQUEST)

        return Response(status=status.HTTP_204_NO_CONTENT)


class InstanceUserActivateEndpoint(BaseAPIView):
    """Restore an account's ability to sign in.

    Memberships stay suspended -- see activate_user() for why -- so workspace access
    is granted again by invitation.
    """

    permission_classes = [InstanceAdminPermission]

    def post(self, request, user_id):
        target = User.objects.filter(pk=user_id, is_bot=False).first()
        if target is None:
            return Response({"error": "User not found."}, status=status.HTTP_404_NOT_FOUND)

        activate_user(target=target)
        return Response(status=status.HTTP_204_NO_CONTENT)
