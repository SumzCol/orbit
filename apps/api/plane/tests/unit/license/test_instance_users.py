# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""The God Mode user list."""

import uuid

import pytest
from django.test import RequestFactory

from plane.db.models import User
from plane.license.api.views import (
    InstanceUserActivateEndpoint,
    InstanceUserDeactivateEndpoint,
    InstanceUserEndpoint,
)
from plane.license.models import Instance, InstanceAdmin


def make_user(email, **kwargs):
    return User.objects.create(email=email, username=uuid.uuid4().hex, **kwargs)


@pytest.fixture
def instance(db):
    return Instance.objects.create(
        instance_name="test",
        instance_id=uuid.uuid4().hex,
        current_version="1.0.0",
        last_checked_at="2026-01-01T00:00:00Z",
    )


def listing(admin):
    """Call the endpoint as `admin` and return the serialized rows."""
    request = RequestFactory().get("/api/instances/users/")
    request.user = admin
    response = InstanceUserEndpoint().dispatch(request)
    assert response.status_code == 200, response.data
    return response.data["results"]


@pytest.mark.unit
@pytest.mark.django_db
class TestInstanceUserEndpoint:
    def test_lists_users_with_their_account_type(self, instance):
        admin = make_user("admin@example.com")
        make_user("member@example.com")
        admin_row = InstanceAdmin.objects.create(instance=instance, user=admin, role=20)

        rows = {r["email"]: r for r in listing(admin)}

        assert rows["admin@example.com"]["is_instance_admin"] is True
        # The pk demotion addresses, which the UI cannot construct without.
        assert str(rows["admin@example.com"]["instance_admin_id"]) == str(admin_row.id)
        assert rows["member@example.com"]["is_instance_admin"] is False
        assert rows["member@example.com"]["instance_admin_id"] is None

    def test_bots_are_excluded(self, instance):
        admin = make_user("admin@example.com")
        InstanceAdmin.objects.create(instance=instance, user=admin, role=20)
        make_user("bot@localhost", is_bot=True)

        assert "bot@localhost" not in {r["email"] for r in listing(admin)}

    def test_search_matches_email_and_names(self, instance):
        admin = make_user("admin@example.com")
        InstanceAdmin.objects.create(instance=instance, user=admin, role=20)
        make_user("ada@lovelace.test", first_name="Ada", last_name="Lovelace", display_name="ada")
        make_user("grace@hopper.test", first_name="Grace", last_name="Hopper", display_name="grace")

        def search(term):
            request = RequestFactory().get("/api/instances/users/", {"search": term})
            request.user = admin
            return {r["email"] for r in InstanceUserEndpoint().dispatch(request).data["results"]}

        assert search("lovelace") == {"ada@lovelace.test"}  # email
        assert search("Grace") == {"grace@hopper.test"}  # first name
        assert search("Hopper") == {"grace@hopper.test"}  # last name

    def test_deactivated_state_needs_both_fields(self, instance):
        """`is_active` alone is ambiguous: a provisioned account has it false while
        having never been deactivated. The pair is what the sign-in guard reads."""
        from django.utils import timezone

        admin = make_user("admin@example.com")
        InstanceAdmin.objects.create(instance=instance, user=admin, role=20)
        make_user("never@example.com", is_active=False)
        make_user("gone@example.com", is_active=False, last_logout_time=timezone.now())

        rows = {r["email"]: r for r in listing(admin)}
        assert rows["never@example.com"]["is_deactivated"] is False
        assert rows["gone@example.com"]["is_deactivated"] is True

    def test_password_autoset_is_exposed(self, instance):
        """God Mode authenticates by password alone, so an account provisioned through
        a provider cannot sign in there even once it is an admin. The list carries the
        flag so the interface can warn before someone is locked out."""
        admin = make_user("admin@example.com")
        InstanceAdmin.objects.create(instance=instance, user=admin, role=20)
        make_user("oidc@example.com", is_password_autoset=True)

        rows = {r["email"]: r for r in listing(admin)}
        assert rows["oidc@example.com"]["is_password_autoset"] is True
        assert rows["admin@example.com"]["is_password_autoset"] is False

    def test_a_non_admin_is_refused(self, instance):
        member = make_user("member@example.com")
        request = RequestFactory().get("/api/instances/users/")
        request.user = member
        assert InstanceUserEndpoint().dispatch(request).status_code == 403


def call(view, admin, target_id):
    request = RequestFactory().post(f"/api/instances/users/{target_id}/")
    request.user = admin
    return view().dispatch(request, user_id=target_id)


@pytest.mark.unit
@pytest.mark.django_db
class TestDeactivateEndpoint:
    def test_an_admin_can_deactivate_a_member(self, instance):
        admin = make_user("admin@example.com")
        InstanceAdmin.objects.create(instance=instance, user=admin, role=20)
        target = make_user("target@example.com")

        assert call(InstanceUserDeactivateEndpoint, admin, target.id).status_code == 204
        target.refresh_from_db()
        assert target.is_active is False
        assert target.last_logout_time is not None

    def test_an_admin_cannot_deactivate_themselves(self, instance):
        """Doing so would drop God Mode access along with the account, leaving no way
        to undo it from the interface that did it."""
        admin = make_user("admin@example.com")
        InstanceAdmin.objects.create(instance=instance, user=admin, role=20)

        response = call(InstanceUserDeactivateEndpoint, admin, admin.id)
        assert response.status_code == 400
        assert "your own account" in response.data["error"]

        admin.refresh_from_db()
        assert admin.is_active is True

    def test_another_instance_admin_is_refused(self, instance):
        admin = make_user("admin@example.com")
        other_admin = make_user("other@example.com")
        InstanceAdmin.objects.create(instance=instance, user=admin, role=20)
        InstanceAdmin.objects.create(instance=instance, user=other_admin, role=20)

        response = call(InstanceUserDeactivateEndpoint, admin, other_admin.id)
        assert response.status_code == 400
        assert "admin access" in response.data["error"]

    def test_a_missing_user_is_404(self, instance):
        import uuid as _uuid

        admin = make_user("admin@example.com")
        InstanceAdmin.objects.create(instance=instance, user=admin, role=20)
        assert call(InstanceUserDeactivateEndpoint, admin, _uuid.uuid4()).status_code == 404

    def test_a_bot_cannot_be_targeted(self, instance):
        admin = make_user("admin@example.com")
        InstanceAdmin.objects.create(instance=instance, user=admin, role=20)
        bot = make_user("bot@localhost", is_bot=True)
        assert call(InstanceUserDeactivateEndpoint, admin, bot.id).status_code == 404

    def test_password_autoset_is_exposed(self, instance):
        """God Mode authenticates by password alone, so an account provisioned through
        a provider cannot sign in there even once it is an admin. The list carries the
        flag so the interface can warn before someone is locked out."""
        admin = make_user("admin@example.com")
        InstanceAdmin.objects.create(instance=instance, user=admin, role=20)
        make_user("oidc@example.com", is_password_autoset=True)

        rows = {r["email"]: r for r in listing(admin)}
        assert rows["oidc@example.com"]["is_password_autoset"] is True
        assert rows["admin@example.com"]["is_password_autoset"] is False

    def test_a_non_admin_is_refused(self, instance):
        member = make_user("member@example.com")
        target = make_user("target@example.com")
        assert call(InstanceUserDeactivateEndpoint, member, target.id).status_code == 403


@pytest.mark.unit
@pytest.mark.django_db
class TestActivateEndpoint:
    def test_it_restores_sign_in(self, instance):
        from plane.utils.user_deactivation import deactivate_user

        admin = make_user("admin@example.com")
        InstanceAdmin.objects.create(instance=instance, user=admin, role=20)
        target = make_user("target@example.com")
        deactivate_user(target=target)

        assert call(InstanceUserActivateEndpoint, admin, target.id).status_code == 204

        target.refresh_from_db()
        assert target.is_active is True
        assert target.last_logout_time is None

    def test_password_autoset_is_exposed(self, instance):
        """God Mode authenticates by password alone, so an account provisioned through
        a provider cannot sign in there even once it is an admin. The list carries the
        flag so the interface can warn before someone is locked out."""
        admin = make_user("admin@example.com")
        InstanceAdmin.objects.create(instance=instance, user=admin, role=20)
        make_user("oidc@example.com", is_password_autoset=True)

        rows = {r["email"]: r for r in listing(admin)}
        assert rows["oidc@example.com"]["is_password_autoset"] is True
        assert rows["admin@example.com"]["is_password_autoset"] is False

    def test_a_non_admin_is_refused(self, instance):
        member = make_user("member@example.com")
        target = make_user("target@example.com")
        assert call(InstanceUserActivateEndpoint, member, target.id).status_code == 403
