"""
Desktop authentication + role-based permissions.

v0.1.3 scope:
  • Multiple users per society DB, each with a role.
  • Username/password login at app start (after CompanyDialog).
  • In-memory AuthSession passed down to RWAMainWindow and pages.
  • Per-action permission checks via `auth.can(perm)`.

Passwords are PBKDF2-HMAC-SHA256, 600 000 iterations (OWASP 2024
recommendation for SHA-256), with a per-user 16-byte salt. Stored as
``pbkdf2:<iters>:<hex_salt>:<hex_hash>`` so the format is
self-describing and we can bump iterations later without a migration.

There is no cross-session "remember me" — close the app, log in
again. The session is in-process only; nothing writes it to disk
beyond updating last_login_at on the user row.
"""
from __future__ import annotations

import hashlib
import hmac
import logging
import os
import secrets
from dataclasses import dataclass
from typing import Optional


logger = logging.getLogger(__name__)


VALID_ROLES = ("admin", "treasurer", "secretary", "auditor")


# Permission matrix. Keys are stable string identifiers used in
# `auth.can("...")` checks across the codebase — pages reference
# these by name, so renaming a key requires grepping for it.
#
# Roles not listed for a permission do NOT have it.
_ROLE_PERMISSIONS: dict[str, set[str]] = {
    "admin": {
        # Admin can do everything; listed explicitly so the matrix is
        # readable instead of relying on a wildcard fallback.
        "manage_users", "view_audit",
        "edit_flats", "edit_members",
        "edit_notices", "edit_complaints", "edit_broadcasts",
        "send_broadcasts", "edit_polls", "edit_visitors",
        "edit_settings", "edit_accounts",
    },
    "treasurer": {
        # Financial side + broadcasts. Cannot manage users / cannot
        # touch accounting *setup* (chart of accounts), but can post
        # vouchers (handled at AG level — RWAGenie defers to AG pages
        # for accounting screens).
        "edit_flats", "edit_members",
        "edit_broadcasts", "send_broadcasts",
        "edit_accounts",
    },
    "secretary": {
        # Resident-facing operations.
        "edit_members",
        "edit_notices", "edit_complaints", "edit_broadcasts",
        "send_broadcasts", "edit_polls", "edit_visitors",
    },
    "auditor": {
        # Read-only. Has view-audit but no edit perms.
        "view_audit",
    },
}

# Default admin seed used on fresh society DBs. Users page nags the
# admin to change it; we intentionally don't force a change-on-first-
# login flow in v0.1.3 to keep the LoginDialog single-purpose.
SEED_ADMIN_USERNAME = "admin"
SEED_ADMIN_PASSWORD = "admin"


# ── Password hashing ────────────────────────────────────────────────────

_HASH_ITERS = 600_000


def _hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"),
                              salt, _HASH_ITERS)
    return f"pbkdf2:{_HASH_ITERS}:{salt.hex()}:{dk.hex()}"


def _verify_password(password: str, stored: str) -> bool:
    try:
        scheme, iters_s, salt_hex, hash_hex = stored.split(":", 3)
    except ValueError:
        return False
    if scheme != "pbkdf2":
        return False
    try:
        iters = int(iters_s)
        salt  = bytes.fromhex(salt_hex)
        want  = bytes.fromhex(hash_hex)
    except ValueError:
        return False
    got = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"),
                               salt, iters)
    return hmac.compare_digest(got, want)


# ── Session ─────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class AuthSession:
    """The currently-logged-in user, attached to RWAMainWindow.

    Pages reach this via ``self.parent().auth`` or via a constructor
    arg where it matters. Frozen so a page can't accidentally
    'promote' itself by mutating the role.
    """
    user_id:    int
    username:   str
    role:       str
    full_name:  str = ""

    def can(self, permission: str) -> bool:
        return permission in _ROLE_PERMISSIONS.get(self.role, set())

    def is_admin(self) -> bool:
        return self.role == "admin"

    def label(self) -> str:
        """Compact label for the title bar / status corner."""
        name = self.full_name or self.username
        return f"{name} ({self.role})"


# ── Service ─────────────────────────────────────────────────────────────

class UserService:
    """CRUD + auth for rwa_users.

    Constructed once per (db, company_id). All operations are scoped
    to the company — switching societies in the same launch (if we
    ever support it) requires a fresh UserService.
    """

    def __init__(self, db, company_id: int):
        self.db = db
        self.company_id = company_id

    # ── Seeding & lookup ───────────────────────────────────────────────

    def seed_default_admin_if_empty(self) -> bool:
        """If no users exist for this company, create admin/admin.
        Returns True if seeding happened. Called from the login flow
        so a fresh society always has a usable login."""
        existing = self.db.execute(
            "SELECT COUNT(*) AS c FROM rwa_users WHERE company_id=?",
            (self.company_id,),
        ).fetchone()
        if (existing["c"] or 0) > 0:
            return False
        self.db.execute(
            """INSERT INTO rwa_users
               (company_id, username, password_hash, role, full_name)
               VALUES (?,?,?,?,?)""",
            (self.company_id, SEED_ADMIN_USERNAME,
             _hash_password(SEED_ADMIN_PASSWORD), "admin",
             "Default Administrator"),
        )
        self.db.commit()
        logger.info("Seeded default admin user for company %d",
                    self.company_id)
        return True

    def list(self) -> list[dict]:
        rows = self.db.execute(
            """SELECT id, username, role, full_name, email, active,
                      last_login_at, created_at
                 FROM rwa_users
                WHERE company_id=?
             ORDER BY active DESC, role, username""",
            (self.company_id,),
        ).fetchall()
        return [dict(r) for r in rows]

    def get(self, user_id: int) -> Optional[dict]:
        row = self.db.execute(
            "SELECT * FROM rwa_users WHERE id=? AND company_id=?",
            (user_id, self.company_id),
        ).fetchone()
        return dict(row) if row else None

    # ── Auth ───────────────────────────────────────────────────────────

    def authenticate(self, username: str, password: str
                     ) -> Optional[AuthSession]:
        row = self.db.execute(
            """SELECT id, username, password_hash, role, full_name, active
                 FROM rwa_users
                WHERE company_id=? AND username=?""",
            (self.company_id, (username or "").strip()),
        ).fetchone()
        if row is None:
            return None
        if not row["active"]:
            return None
        if not _verify_password(password or "", row["password_hash"]):
            return None
        self.db.execute(
            "UPDATE rwa_users SET last_login_at=datetime('now') WHERE id=?",
            (row["id"],),
        )
        self.db.commit()
        return AuthSession(
            user_id=row["id"], username=row["username"], role=row["role"],
            full_name=row["full_name"] or "",
        )

    # ── User management (admin-only — callers must check perm) ─────────

    def add(self, *, username: str, password: str, role: str,
            full_name: str = "", email: str = "") -> int:
        username = (username or "").strip()
        if not username:
            raise ValueError("Username is required.")
        if role not in VALID_ROLES:
            raise ValueError(f"role must be one of {VALID_ROLES}")
        if not password or len(password) < 4:
            raise ValueError("Password must be at least 4 characters.")
        dupe = self.db.execute(
            "SELECT id FROM rwa_users WHERE company_id=? AND username=?",
            (self.company_id, username),
        ).fetchone()
        if dupe:
            raise ValueError(f"Username '{username}' already exists.")
        cur = self.db.execute(
            """INSERT INTO rwa_users
               (company_id, username, password_hash, role, full_name, email)
               VALUES (?,?,?,?,?,?)""",
            (self.company_id, username, _hash_password(password),
             role, full_name or "", email or ""),
        )
        self.db.commit()
        return cur.lastrowid

    def update(self, user_id: int, *,
               role: Optional[str] = None,
               full_name: Optional[str] = None,
               email: Optional[str] = None,
               active: Optional[bool] = None) -> None:
        sets: list[str] = []
        params: list = []
        if role is not None:
            if role not in VALID_ROLES:
                raise ValueError(f"role must be one of {VALID_ROLES}")
            sets.append("role=?"); params.append(role)
        if full_name is not None:
            sets.append("full_name=?"); params.append(full_name)
        if email is not None:
            sets.append("email=?"); params.append(email)
        if active is not None:
            sets.append("active=?"); params.append(1 if active else 0)
        if not sets:
            return
        params.extend([user_id, self.company_id])
        self.db.execute(
            f"UPDATE rwa_users SET {', '.join(sets)} "
            "WHERE id=? AND company_id=?",
            params,
        )
        self.db.commit()

    def set_password(self, user_id: int, new_password: str) -> None:
        if not new_password or len(new_password) < 4:
            raise ValueError("Password must be at least 4 characters.")
        self.db.execute(
            "UPDATE rwa_users SET password_hash=? "
            "WHERE id=? AND company_id=?",
            (_hash_password(new_password), user_id, self.company_id),
        )
        self.db.commit()

    def delete(self, user_id: int) -> None:
        """Soft-delete: set active=0. Hard-delete would orphan
        audit-log rows by FK; the username column on rwa_audit_log
        is denormalised so a real DELETE would still leave readable
        history, but soft-delete is friendlier (typo recovery)."""
        self.db.execute(
            "UPDATE rwa_users SET active=0 "
            "WHERE id=? AND company_id=?",
            (user_id, self.company_id),
        )
        self.db.commit()

    def count_active_admins(self) -> int:
        """Used to refuse the demote/disable that would leave the
        society with zero admins."""
        r = self.db.execute(
            "SELECT COUNT(*) AS c FROM rwa_users "
            "WHERE company_id=? AND active=1 AND role='admin'",
            (self.company_id,),
        ).fetchone()
        return r["c"] or 0
