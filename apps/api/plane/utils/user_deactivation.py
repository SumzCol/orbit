# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Deactivating and reactivating a user account.

Shared by the self-service endpoint and the God Mode one so the two cannot drift.
Everything here acts on `target`; nothing reads the requesting user. That distinction
is the whole reason this is a function: the logic it was extracted from was written
for self-service and reached for `request.user` in places where it meant "the account
being deactivated". Identical when you deactivate yourself, wrong when an
administrator deactivates somebody else -- it would have suspended the administrator's
own memberships and dropped their sessions while flagging the target's account.
"""

# Python imports
import uuid

# Django imports
from django.db.models import Count, Q
from django.utils import timezone

# Module imports
from plane.db.models import (
    Profile,
    ProjectMember,
    Session,
    WorkspaceMember,
    WorkspaceMemberInvite,
)
from plane.license.models import InstanceAdmin


# Role 20 is Admin on both ProjectMember and WorkspaceMember.
ADMIN_ROLE = 20


def _memberships_to_suspend(model, parent_field, target):
    """Return the memberships to stand down, or None if that would orphan something.

    A membership can be suspended when somebody else administers that project or
    workspace, or when the target is its only member. Otherwise deactivating would
    leave it with nobody able to administer it.

    Counted with an explicit query per membership rather than the annotation this was
    extracted from. That annotation aggregated over the target's own row -- Django
    groups by the row's pk -- so `total_members` was always 1, the "only member"
    branch always matched, and the refusal was unreachable. The guard has therefore
    never actually fired; this is the first version that does.
    """
    to_suspend = []
    for membership in model.objects.filter(member=target, is_active=True):
        # Both numbers come from one aggregate rather than two count() calls: they are
        # different counts, not a repeat, so neither can be reused for the other.
        siblings = model.objects.filter(is_active=True, **{parent_field: getattr(membership, parent_field)}).aggregate(
            total=Count("id"),
            other_admins=Count("id", filter=Q(role=ADMIN_ROLE) & ~Q(member_id=target.id)),
        )

        if siblings["other_admins"] > 0 or siblings["total"] == 1:
            membership.is_active = False
            to_suspend.append(membership)
        else:
            return None
    return to_suspend


def deactivate_user(*, target, actor=None, request=None):
    """Deactivate `target`, or explain why it cannot be done.

    Returns None when the account was deactivated, otherwise a message naming the
    reason. HTTP shaping is left to the caller.

    `actor` is whoever asked; it defaults to the target for self-service. It is used
    only to decide whether `last_logout_ip` describes this event -- an administrator's
    address says nothing about where the target last signed out, so it is left alone.
    """
    actor = actor or target

    if InstanceAdmin.objects.filter(user=target).exists():
        return "Instance admins cannot be deactivated. Remove admin access first."

    projects_to_suspend = _memberships_to_suspend(ProjectMember, "project_id", target)
    if projects_to_suspend is None:
        return "This account is the only admin of one or more projects."

    workspaces_to_suspend = _memberships_to_suspend(WorkspaceMember, "workspace_id", target)
    if workspaces_to_suspend is None:
        return "This account is the only admin of one or more workspaces."

    ProjectMember.objects.bulk_update(projects_to_suspend, ["is_active"], batch_size=100)
    WorkspaceMember.objects.bulk_update(workspaces_to_suspend, ["is_active"], batch_size=100)

    WorkspaceMemberInvite.objects.filter(email=target.email).delete()
    Session.objects.filter(user_id=target.id).delete()

    profile, _ = Profile.objects.get_or_create(user=target)
    profile.last_workspace_id = None
    profile.is_tour_completed = False
    profile.is_onboarded = False
    profile.onboarding_step = {
        "workspace_join": False,
        "profile_complete": False,
        "workspace_create": False,
        "workspace_invite": False,
    }
    profile.save()

    target.is_password_autoset = True
    target.set_password(uuid.uuid4().hex)

    target.is_active = False
    # Only meaningful when the target signed themselves out. An administrator's IP
    # would misdescribe where this account was last used.
    if request is not None and actor.id == target.id:
        from plane.authentication.utils.host import user_ip

        target.last_logout_ip = user_ip(request=request)
    target.last_logout_time = timezone.now()
    target.save()

    return None


def activate_user(*, target):
    """Restore the ability to sign in. Memberships are deliberately left suspended.

    Both fields are required. The sign-in guard refuses when `is_active` is false *and*
    `last_logout_time` is set, so clearing only the flag would leave the account
    looking active in the admin list while still being turned away at sign-in
    (GHSA-rmmf-rj2q-3rrg).

    Deactivation stood down every project and workspace membership, and nothing records
    which of them it turned off versus which were already inactive because the person
    had left. Restoring them all would silently return people to workspaces they had
    exited, so access is re-granted by invitation instead.
    """
    target.is_active = True
    target.last_logout_time = None
    target.save()
