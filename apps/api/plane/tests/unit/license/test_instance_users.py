# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""The God Mode user list."""

import uuid

import pytest
from django.test import RequestFactory

from plane.db.models import User
from plane.license.api.views import (
    InstanceAdminEndpoint,
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

    def test_the_second_page_continues_where_the_first_stopped(self, instance):
        """The list is cursor paginated and the interface has a Load more button, so the
        second page has to carry the rest rather than repeat the first."""
        admin = make_user("admin@example.com")
        InstanceAdmin.objects.create(instance=instance, user=admin, role=20)
        for i in range(6):
            make_user(f"user{i}@example.com")

        def page(cursor):
            request = RequestFactory().get("/api/instances/users/", {"cursor": cursor, "per_page": 3})
            request.user = admin
            return InstanceUserEndpoint().dispatch(request).data

        first = page("3:0:0")
        assert len(first["results"]) == 3
        assert first["total_count"] == 7  # six members plus the admin
        assert first["next_page_results"] is True

        second = page(first["next_cursor"])
        assert len(second["results"]) == 3

        first_emails = {r["email"] for r in first["results"]}
        second_emails = {r["email"] for r in second["results"]}
        assert first_emails.isdisjoint(second_emails)

        last = page(second["next_cursor"])
        assert len(last["results"]) == 1
        assert last["next_page_results"] is False
        # Every account is reachable by paging, none twice.
        assert len(first_emails | second_emails | {r["email"] for r in last["results"]}) == 7

    def test_admin_rows_are_scoped_to_the_active_instance(self, instance):
        """The annotated id is handed straight to InstanceAdminEndpoint.delete, which
        filters on the active instance. An id from another Instance row would make
        revoking answer 204 while deleting nothing, so it must not be reported here."""
        admin = make_user("admin@example.com")
        InstanceAdmin.objects.create(instance=instance, user=admin, role=20)

        # Instance orders by -created_at, so build the stray row first to be sure the
        # fixture instance stays the one Instance.objects.first() returns.
        stray = Instance.objects.create(
            instance_name="stray",
            instance_id=uuid.uuid4().hex,
            current_version="1.0.0",
            last_checked_at="2025-01-01T00:00:00Z",
        )
        Instance.objects.filter(pk=stray.pk).update(created_at="2020-01-01T00:00:00Z")
        assert Instance.objects.first().pk == instance.pk

        elsewhere = make_user("elsewhere@example.com")
        InstanceAdmin.objects.create(instance=stray, user=elsewhere, role=20)

        rows = {r["email"]: r for r in listing(admin)}
        assert rows["elsewhere@example.com"]["is_instance_admin"] is False
        assert rows["elsewhere@example.com"]["instance_admin_id"] is None
        assert rows["admin@example.com"]["is_instance_admin"] is True

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

    def test_a_non_admin_is_refused(self, instance):
        member = make_user("member@example.com")
        target = make_user("target@example.com")
        assert call(InstanceUserActivateEndpoint, member, target.id).status_code == 403


@pytest.mark.unit
@pytest.mark.django_db
class TestInstanceAdminGrant:
    """Granting admin access to someone who held it before.

    InstanceAdmin is soft-deleted while unique_together (instance, user) is a plain
    database constraint, so a revoked grant leaves a tombstone that a plain create()
    collides with. The collision surfaced as "The payload is not valid" and made the
    grant permanently unreachable for anyone ever demoted.
    """

    def _post(self, admin, email):
        request = RequestFactory().post("/api/instances/admins/", {"email": email, "role": 20})
        request.user = admin
        return InstanceAdminEndpoint().dispatch(request)

    def test_a_revoked_admin_can_be_granted_again(self, instance):
        admin = make_user("admin@example.com")
        InstanceAdmin.objects.create(instance=instance, user=admin, role=20)
        target = make_user("target@example.com")

        InstanceAdmin.objects.create(instance=instance, user=target, role=20)
        # Exactly what InstanceAdminEndpoint.delete does: a queryset delete, which the
        # soft-deletion queryset turns into `update(deleted_at=now)`.
        InstanceAdmin.objects.filter(instance=instance, user=target).delete()
        assert InstanceAdmin.all_objects.filter(user=target).count() == 1

        response = self._post(admin, "target@example.com")

        assert response.status_code == 201, response.data
        # The tombstone is revived rather than duplicated.
        assert InstanceAdmin.all_objects.filter(user=target).count() == 1
        assert InstanceAdmin.objects.filter(user=target).count() == 1

    def test_granting_twice_is_refused_rather_than_crashing(self, instance):
        admin = make_user("admin@example.com")
        InstanceAdmin.objects.create(instance=instance, user=admin, role=20)
        target = make_user("target@example.com")
        InstanceAdmin.objects.create(instance=instance, user=target, role=20)

        response = self._post(admin, "target@example.com")

        assert response.status_code == 409, response.data
        assert InstanceAdmin.objects.filter(user=target).count() == 1

    def test_a_first_time_grant_still_works(self, instance):
        admin = make_user("admin@example.com")
        InstanceAdmin.objects.create(instance=instance, user=admin, role=20)
        make_user("target@example.com")

        response = self._post(admin, "target@example.com")

        assert response.status_code == 201, response.data
        assert InstanceAdmin.objects.filter(user__email="target@example.com").count() == 1
