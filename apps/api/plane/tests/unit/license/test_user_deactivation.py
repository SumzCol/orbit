# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""The shared deactivate/activate helper.

The first test here is the reason the helper exists. The logic it was extracted from
was written for self-service and read `request.user` where it meant "the account being
deactivated" -- indistinguishable when you deactivate yourself, and wrong when an
administrator deactivates somebody else.
"""

import uuid

import pytest
from django.utils import timezone

from plane.db.models import (
    Profile,
    Session,
    User,
    Workspace,
    WorkspaceMember,
    WorkspaceMemberInvite,
)
from plane.license.models import Instance, InstanceAdmin
from plane.utils.user_deactivation import activate_user, deactivate_user

ADMIN, MEMBER = 20, 15


def make_user(email):
    user = User.objects.create(email=email, username=uuid.uuid4().hex)
    Profile.objects.get_or_create(user=user)
    return user


def make_workspace(owner, slug, members):
    workspace = Workspace.objects.create(name=slug, slug=slug, owner=owner)
    for user, role in members:
        WorkspaceMember.objects.create(workspace=workspace, member=user, role=role)
    return workspace


@pytest.fixture
def instance(db):
    return Instance.objects.create(
        instance_name="t",
        instance_id=uuid.uuid4().hex,
        current_version="1.0.0",
        last_checked_at=timezone.now(),
    )


@pytest.mark.unit
@pytest.mark.django_db
class TestDeactivateUser:
    def test_only_the_targets_memberships_and_sessions_are_touched(self):
        """The bug the extraction exists to prevent."""
        actor = make_user("admin@example.com")
        target = make_user("target@example.com")
        other = make_user("other@example.com")
        make_workspace(other, "acme", [(other, ADMIN), (actor, ADMIN), (target, MEMBER)])

        Session.objects.create(session_key="actor-key", user_id=actor.id, session_data="", expire_date=timezone.now())
        Session.objects.create(session_key="target-key", user_id=target.id, session_data="", expire_date=timezone.now())

        assert deactivate_user(target=target, actor=actor) is None

        assert WorkspaceMember.objects.get(member=target).is_active is False
        assert WorkspaceMember.objects.get(member=actor).is_active is True, "the actor was suspended"
        assert Session.objects.filter(user_id=actor.id).exists(), "the actor was signed out"
        assert not Session.objects.filter(user_id=target.id).exists()

        actor.refresh_from_db()
        assert actor.is_active is True, "the actor was deactivated"

    def test_it_deactivates_the_target(self):
        target = make_user("target@example.com")
        assert deactivate_user(target=target) is None

        target.refresh_from_db()
        assert target.is_active is False
        assert target.last_logout_time is not None
        assert target.is_password_autoset is True

    def test_pending_invitations_are_dropped(self):
        owner = make_user("owner@example.com")
        workspace = make_workspace(owner, "acme", [(owner, ADMIN)])
        target = make_user("target@example.com")
        WorkspaceMemberInvite.objects.create(email=target.email, workspace=workspace, role=MEMBER, token="tok")

        deactivate_user(target=target)
        assert not WorkspaceMemberInvite.objects.filter(email=target.email).exists()

    def test_an_instance_admin_is_refused(self, instance):
        target = make_user("admin@example.com")
        InstanceAdmin.objects.create(instance=instance, user=target, role=20)

        message = deactivate_user(target=target)
        assert message and "admin access" in message
        target.refresh_from_db()
        assert target.is_active is True

    def test_the_sole_workspace_admin_is_refused_and_nothing_changes(self):
        target = make_user("target@example.com")
        member = make_user("member@example.com")
        make_workspace(target, "acme", [(target, ADMIN), (member, MEMBER)])

        message = deactivate_user(target=target)
        assert message and "workspaces" in message

        target.refresh_from_db()
        assert target.is_active is True, "refused but still deactivated"
        assert WorkspaceMember.objects.get(member=target).is_active is True

    def test_the_last_member_of_a_workspace_may_leave(self):
        """Sole admin of a workspace nobody else belongs to is not a lock-out."""
        target = make_user("target@example.com")
        make_workspace(target, "solo", [(target, ADMIN)])

        assert deactivate_user(target=target) is None
        target.refresh_from_db()
        assert target.is_active is False


@pytest.mark.unit
@pytest.mark.django_db
class TestActivateUser:
    def test_it_clears_both_fields_the_sign_in_guard_reads(self):
        target = make_user("target@example.com")
        deactivate_user(target=target)

        activate_user(target=target)

        target.refresh_from_db()
        assert target.is_active is True
        # Without this the account looks active in the list but is still turned away.
        assert target.last_logout_time is None

    def test_memberships_stay_suspended(self):
        """Documented v1 behaviour: activation restores sign-in, not access.

        Nothing records which memberships deactivation turned off, so restoring them
        would return people to workspaces they had already left.
        """
        owner = make_user("owner@example.com")
        target = make_user("target@example.com")
        make_workspace(owner, "acme", [(owner, ADMIN), (target, MEMBER)])

        deactivate_user(target=target)
        activate_user(target=target)

        assert WorkspaceMember.objects.get(member=target).is_active is False
