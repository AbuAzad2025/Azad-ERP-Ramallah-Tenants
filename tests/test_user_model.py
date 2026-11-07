from datetime import datetime, timezone
import pytest
from werkzeug.security import check_password_hash


class TestUserModel:

    def test_create_minimal_user(self, db_session):
        from models import User
        u = User(username="testuser", email="test@example.com", password_hash="abc")
        db_session.add(u)
        db_session.commit()
        assert u.id is not None
        assert u.username == "testuser"
        assert u.email == "test@example.com"
        assert u.password_hash == "abc"

    def test_email_validator_strips_and_lowers(self, db_session):
        from models import User
        u = User(username="emailtest", email="  Test@Example.COM  ", password_hash="x")
        db_session.add(u)
        db_session.commit()
        assert u.email == "test@example.com"

    def test_username_validator_strips(self, db_session):
        from models import User
        u = User(username="  spaced  ", email="spaced@test.com", password_hash="x")
        db_session.add(u)
        db_session.commit()
        assert u.username == "spaced"

    def test_column_defaults(self, db_session):
        from models import User
        u = User(username="defaults", email="defaults@test.com", password_hash="x")
        db_session.add(u)
        db_session.commit()
        assert u.is_active is True
        assert u.is_system_account is False
        assert u.login_count == 0
        assert u.totp_enabled is False

    def test_nullable_columns(self, db_session):
        from models import User
        u = User(username="nullable", email="nullable@test.com", password_hash="x")
        db_session.add(u)
        db_session.commit()
        assert u.last_login is None
        assert u.last_seen is None
        assert u.last_login_ip is None
        assert u.avatar_url is None
        assert u.notes_text is None
        assert u.totp_secret is None
        assert u.login_schedule_json is None
        assert u.allowed_stations_json is None

    def test_timestamps(self, db_session):
        from models import User
        u = User(username="ts", email="ts@test.com", password_hash="x")
        db_session.add(u)
        db_session.commit()
        assert isinstance(u.created_at, datetime)
        assert isinstance(u.updated_at, datetime)

    def test_unique_username_enforced(self, db_session):
        from models import User
        from sqlalchemy.exc import IntegrityError
        u1 = User(username="unique", email="u1@test.com", password_hash="x")
        db_session.add(u1)
        db_session.commit()
        u2 = User(username="unique", email="u2@test.com", password_hash="x")
        db_session.add(u2)
        with pytest.raises(IntegrityError):
            db_session.commit()
        db_session.rollback()

    def test_unique_email_enforced(self, db_session):
        from models import User
        from sqlalchemy.exc import IntegrityError
        u1 = User(username="email1", email="dup@test.com", password_hash="x")
        db_session.add(u1)
        db_session.commit()
        u2 = User(username="email2", email="dup@test.com", password_hash="x")
        db_session.add(u2)
        with pytest.raises(IntegrityError):
            db_session.commit()
        db_session.rollback()

    def test_repr_with_username(self, db_session):
        from models import User
        u = User(username="repruser", email="repr@test.com", password_hash="x")
        assert repr(u) == "<User repruser>"

    def test_repr_without_username(self, db_session):
        from models import User
        u = User(username="", email="repr2@test.com", password_hash="x")
        db_session.add(u)
        db_session.commit()
        assert repr(u) == f"<User {u.id}>"

    def test_role_name_l_without_role(self, db_session):
        from models import User
        u = User(username="norole", email="norole@test.com", password_hash="x")
        assert u.role_name_l == ""

    def test_role_name_l_with_role(self, db_session):
        from models import User, Role
        r = Role(name="Admin")
        db_session.add(r)
        db_session.flush()
        u = User(username="withrole", email="withrole@test.com", password_hash="x", role_id=r.id)
        db_session.add(u)
        db_session.commit()
        assert u.role_name_l == "admin"

    def test_is_system_default_false(self, db_session):
        from models import User
        u = User(username="sysdefault", email="sysdefault@test.com", password_hash="x")
        assert u.is_system is False

    def test_is_system_with_system_account(self, db_session):
        from models import User
        u = User(username="sysacc", email="sysacc@test.com", password_hash="x",
                 is_system_account=True)
        assert u.is_system is True

    def test_is_system_with_owner_username(self, db_session):
        from models import User
        u = User(username="__OWNER__", email="owner@test.com", password_hash="x")
        assert u.is_system is True

    def test_is_super_role_with_super_role(self, db_session):
        from models import User, Role
        r = Role(name="owner")
        db_session.add(r)
        db_session.flush()
        u = User(username="superuser", email="super@test.com", password_hash="x", role_id=r.id)
        db_session.add(u)
        db_session.commit()
        assert u.is_super_role is True

    def test_is_super_role_with_system(self, db_session):
        from models import User
        u = User(username="sys_super", email="sys_super@test.com", password_hash="x",
                 is_system_account=True)
        assert u.is_super_role is True

    def test_is_super_role_false(self, db_session):
        from models import User, Role
        r = Role(name="staff")
        db_session.add(r)
        db_session.flush()
        u = User(username="normal", email="normal@test.com", password_hash="x", role_id=r.id)
        db_session.add(u)
        db_session.commit()
        assert u.is_super_role is False

    def test_is_admin_role_true(self, db_session):
        from models import User, Role
        r = Role(name="admin")
        db_session.add(r)
        db_session.flush()
        u = User(username="adminuser", email="admin@test.com", password_hash="x", role_id=r.id)
        db_session.add(u)
        db_session.commit()
        assert u.is_admin_role is True

    def test_is_admin_role_false(self, db_session):
        from models import User, Role
        r = Role(name="staff")
        db_session.add(r)
        db_session.flush()
        u = User(username="notadmin", email="notadmin@test.com", password_hash="x", role_id=r.id)
        db_session.add(u)
        db_session.commit()
        assert u.is_admin_role is False

    def test_avatar_or_initials_returns_avatar_url(self, db_session):
        from models import User
        u = User(username="avatar", email="avatar@test.com", password_hash="x",
                 avatar_url="https://example.com/avatar.png")
        assert u.avatar_or_initials == "https://example.com/avatar.png"

    def test_avatar_or_initials_from_username(self, db_session):
        from models import User
        u = User(username="john doe", email="jd@test.com", password_hash="x")
        assert u.avatar_or_initials == "JD"

    def test_avatar_or_initials_from_single_username(self, db_session):
        from models import User
        u = User(username="john", email="jd@test.com", password_hash="x")
        assert u.avatar_or_initials == "J"

    def test_avatar_or_initials_from_email(self, db_session):
        from models import User
        u = User(username="", email="jane.doe@test.com", password_hash="x")
        assert u.avatar_or_initials == "J"

    def test_avatar_or_initials_fallback(self, db_session):
        from models import User
        u = User(username="", email="", password_hash="x")
        assert u.avatar_or_initials == "U"

    def test_display_name_from_username(self, db_session):
        from models import User
        u = User(username="johndoe", email="jd@test.com", password_hash="x")
        assert u.display_name == "johndoe"

    def test_display_name_from_email(self, db_session):
        from models import User
        u = User(username="", email="jd@test.com", password_hash="x")
        assert u.display_name == "jd@test.com"

    def test_display_name_fallback(self, db_session):
        from models import User
        u = User(username="", email="", password_hash="x")
        db_session.add(u)
        db_session.commit()
        assert u.display_name == f"User {u.id}"

    def test_set_password(self, db_session):
        from models import User
        u = User(username="setpwd", email="setpwd@test.com", password_hash="x")
        u.set_password("newpassword")
        assert check_password_hash(u.password_hash, "newpassword")

    def test_set_password_empty_raises(self, db_session):
        from models import User
        u = User(username="emptypwd", email="empty@test.com", password_hash="x")
        with pytest.raises(ValueError, match="password required"):
            u.set_password("")
        with pytest.raises(ValueError, match="password required"):
            u.set_password(None)

    def test_set_password_non_string_raises(self, db_session):
        from models import User
        u = User(username="nonstr", email="nonstr@test.com", password_hash="x")
        with pytest.raises(ValueError, match="password required"):
            u.set_password(123)

    def test_check_password_correct(self, db_session):
        from models import User
        u = User(username="checkpw", email="checkpw@test.com", password_hash="x")
        u.set_password("secret")
        assert u.check_password("secret") is True

    def test_check_password_wrong(self, db_session):
        from models import User
        u = User(username="checkwrong", email="checkwrong@test.com", password_hash="x")
        u.set_password("secret")
        assert u.check_password("wrong") is False

    def test_check_password_empty_hash(self, db_session):
        from models import User
        u = User(username="no_hash", email="no_hash@test.com", password_hash="")
        assert u.check_password("anything") is False

    def test_mark_login_sets_last_login_and_last_seen(self, db_session):
        from models import User
        u = User(username="marklogin", email="marklogin@test.com", password_hash="x")
        db_session.add(u)
        db_session.commit()
        before = datetime.now(timezone.utc)
        u.mark_login()
        assert u.last_login is not None
        assert u.last_seen is not None
        assert u.last_login >= before
        assert u.last_seen >= before

    def test_mark_login_with_ip(self, db_session):
        from models import User
        u = User(username="markip", email="markip@test.com", password_hash="x")
        u.mark_login(ip="192.168.1.1")
        assert u.last_login_ip == "192.168.1.1"

    def test_mark_login_increments_count(self, db_session):
        from models import User
        u = User(username="markcount", email="markcount@test.com", password_hash="x")
        u.mark_login()
        assert u.login_count == 1
        u.mark_login()
        assert u.login_count == 2

    def test_has_role_exact_match(self, db_session):
        from models import User, Role
        r = Role(name="Manager")
        db_session.add(r)
        db_session.flush()
        u = User(username="hasrole", email="hasrole@test.com", password_hash="x", role_id=r.id)
        db_session.add(u)
        db_session.commit()
        assert u.has_role("manager") is True

    def test_has_role_no_match(self, db_session):
        from models import User, Role
        r = Role(name="Staff")
        db_session.add(r)
        db_session.flush()
        u = User(username="norolemat", email="norolemat@test.com", password_hash="x", role_id=r.id)
        db_session.add(u)
        db_session.commit()
        assert u.has_role("admin") is False

    def test_has_role_multiple_names(self, db_session):
        from models import User, Role
        r = Role(name="admin")
        db_session.add(r)
        db_session.flush()
        u = User(username="multirole", email="multirole@test.com", password_hash="x", role_id=r.id)
        db_session.add(u)
        db_session.commit()
        assert u.has_role("staff", "admin", "manager") is True

    def test_has_role_empty_ignored(self, db_session):
        from models import User, Role
        r = Role(name="admin")
        db_session.add(r)
        db_session.flush()
        u = User(username="emptyrole", email="emptyrole@test.com", password_hash="x", role_id=r.id)
        db_session.add(u)
        db_session.commit()
        assert u.has_role("") is False

    def test_has_permission_empty_code_false(self, db_session):
        from models import User
        u = User(username="noperm", email="noperm@test.com", password_hash="x")
        assert u.has_permission("") is False

    def test_has_permission_super_role_true(self, db_session):
        from models import User, Role
        r = Role(name="owner")
        db_session.add(r)
        db_session.flush()
        u = User(username="superperm", email="superperm@test.com", password_hash="x",
                 role_id=r.id)
        db_session.add(u)
        db_session.commit()
        assert u.has_permission("anything") is True

    def test_has_permission_system_user_true(self, db_session):
        from models import User
        u = User(username="sysperm", email="sysperm@test.com", password_hash="x",
                 is_system_account=True)
        assert u.has_permission("anything") is True

    def test_has_permission_owner_username_true(self, db_session):
        from models import User
        u = User(username="__OWNER__", email="own@test.com", password_hash="x")
        assert u.has_permission("anything") is True

    def test_has_permission_non_super_false(self, db_session):
        from models import User, Role
        r = Role(name="staff")
        db_session.add(r)
        db_session.flush()
        u = User(username="nonsuper", email="nonsuper@test.com", password_hash="x",
                 role_id=r.id)
        db_session.add(u)
        db_session.commit()
        assert u.has_permission("some_permission") is False

    def test_has_permission_with_role_permission(self):
        """Verify has_permission delegates to _get_user_permissions for non-super users."""
        from unittest.mock import patch
        from models import User
        u = User(username="u", email="u@u.com", password_hash="x")
        with patch("utils._get_user_permissions", return_value={"test_code"}):
            assert u.has_permission("test_code") is True
            assert u.has_permission("other_code") is False

    def test_touch(self):
        from models import User
        u = User(username="touchuser", email="touchuser@test.com", password_hash="x")
        before = datetime.now(timezone.utc)
        u.touch()
        assert u.last_seen is not None
        assert u.last_seen >= before

    def test_user_mixin_is_authenticated(self, db_session):
        from models import User
        u = User(username="mixin", email="mixin@test.com", password_hash="x")
        db_session.add(u)
        db_session.commit()
        assert u.is_authenticated is True

    def test_user_mixin_is_anonymous(self):
        from models import User
        u = User(username="anontest", email="anon@test.com", password_hash="x")
        assert u.is_anonymous is False

    def test_user_mixin_get_id(self, db_session):
        from models import User
        u = User(username="getid", email="getid@test.com", password_hash="x")
        db_session.add(u)
        db_session.commit()
        assert u.get_id() == str(u.id)

    def test_is_active_column(self, db_session):
        from models import User
        u = User(username="activecol", email="activecol@test.com", password_hash="x",
                 is_active=False)
        db_session.add(u)
        db_session.commit()
        assert u.is_active is False

    def test_audit_mixin_previous_state_on_update(self, db_session):
        from models import User
        u = User(username="audit", email="audit@test.com", password_hash="x")
        db_session.add(u)
        db_session.commit()
        u.username = "audit_updated"
        db_session.commit()
        assert hasattr(u, "_previous_state")
        assert u._previous_state.get("username") == "audit"

    def test_role_relationship(self, db_session):
        from models import User, Role
        r = Role(name="Manager")
        db_session.add(r)
        db_session.flush()
        u = User(username="rel_test", email="rel@test.com", password_hash="x",
                 role_id=r.id)
        db_session.add(u)
        db_session.commit()
        assert u.role is r

    def test_extra_permissions_relationship(self, db_session):
        from models import User, Permission
        p = Permission(name="Extra Perm", code="extra_perm")
        db_session.add(p)
        db_session.flush()
        u = User(username="extra_rel", email="extra_rel@test.com", password_hash="x")
        db_session.add(u)
        db_session.flush()
        u.extra_permissions.append(p)
        db_session.commit()
        assert p in list(u.extra_permissions.all())
        assert u in list(p.extra_users.all())


class TestRoleModel:

    def test_create_role(self, db_session):
        from models import Role
        r = Role(name="admin")
        db_session.add(r)
        db_session.commit()
        assert r.id is not None
        assert r.name == "admin"
        assert r.is_default is False

    def test_name_validator_strips(self, db_session):
        from models import Role
        r = Role(name="  Manager  ")
        db_session.add(r)
        db_session.commit()
        assert r.name == "Manager"

    def test_is_default_default(self, db_session):
        from models import Role
        r = Role(name="default_role")
        db_session.add(r)
        db_session.commit()
        assert r.is_default is False

    def test_description(self, db_session):
        from models import Role
        r = Role(name="desc_role", description="Test description")
        db_session.add(r)
        db_session.commit()
        assert r.description == "Test description"

    def test_repr(self):
        from models import Role
        r = Role(name="repr_role")
        assert repr(r) == "<Role repr_role>"

    def test_unique_name_enforced(self, db_session):
        from models import Role
        from sqlalchemy.exc import IntegrityError
        r1 = Role(name="unique_role")
        db_session.add(r1)
        db_session.commit()
        r2 = Role(name="unique_role")
        db_session.add(r2)
        with pytest.raises(IntegrityError):
            db_session.commit()
        db_session.rollback()

    def test_has_permission_empty_false(self):
        from models import Role
        r = Role(name="empty_perm")
        assert r.has_permission("") is False

    def test_has_permission_no_permissions_false(self, db_session):
        from models import Role
        r = Role(name="no_perm_role")
        db_session.add(r)
        db_session.commit()
        assert r.has_permission("view_sales") is False

    def test_has_permission_with_assigned_permission(self, db_session):
        from models import Role, Permission
        r = Role(name="perm_role")
        db_session.add(r)
        p = Permission(name="Sales View", code="view_sales")
        db_session.add(p)
        db_session.flush()
        r.permissions.append(p)
        db_session.commit()
        assert r.has_permission("view_sales") is True

    def test_audit_mixin_previous_state_on_update(self, db_session):
        from models import Role
        r = Role(name="audit_role")
        db_session.add(r)
        db_session.commit()
        r.name = "audit_role_updated"
        db_session.commit()
        assert hasattr(r, "_previous_state")
        assert r._previous_state.get("name") == "audit_role"

    def test_permissions_relationship(self, db_session):
        from models import Role, Permission
        r = Role(name="rel_role")
        db_session.add(r)
        p = Permission(name="Perm A", code="perm_a")
        db_session.add(p)
        db_session.flush()
        r.permissions.append(p)
        db_session.commit()
        assert p in r.permissions
        assert r in p.role_permissions

    def test_users_relationship_backref(self, db_session):
        from models import User, Role
        r = Role(name="user_rel_role")
        db_session.add(r)
        db_session.flush()
        u = User(username="backref_user", email="backref@test.com", password_hash="x",
                 role_id=r.id)
        db_session.add(u)
        db_session.commit()
        assert u in r.users
