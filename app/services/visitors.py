"""
Visitor-pass service — gate-issued or pre-authorised entry passes.

A pass carries: visitor name + phone, target flat, expected arrival
window (`expected_at`/`valid_until`), and a short alphanumeric
`pass_code` the gatekeeper checks. Entry / exit times get stamped
when the visitor actually enters and leaves.
"""
from __future__ import annotations

import secrets
import string
from datetime import datetime
from typing import Optional


VALID_PURPOSES = ("GUEST", "DELIVERY", "SERVICE", "STAFF", "OTHER")

_EDITABLE = {
    "flat_id", "visitor_name", "visitor_phone", "vehicle_no",
    "purpose", "expected_at", "valid_until",
    "entry_time", "exit_time", "pass_code", "issued_by",
}

_PASS_ALPHABET = string.ascii_uppercase.replace("I", "").replace("O", "") + \
                 "23456789"


def _generate_pass_code() -> str:
    return "".join(secrets.choice(_PASS_ALPHABET) for _ in range(6))


class VisitorPassesService:
    def __init__(self, db, company_id: int):
        self.db = db
        self.company_id = company_id

    def list(self, active_only: bool = True) -> list[dict]:
        q = """SELECT v.id, v.flat_id, v.visitor_name, v.visitor_phone,
                      v.vehicle_no, v.purpose,
                      v.expected_at, v.valid_until,
                      v.entry_time, v.exit_time,
                      v.pass_code, v.issued_by, v.created_at,
                      f.flat_no
                 FROM rwa_visitor_passes v
            LEFT JOIN rwa_flats f ON f.id = v.flat_id
                WHERE v.company_id=?"""
        params: list = [self.company_id]
        if active_only:
            # Show only currently valid + recently-used passes by default
            q += """ AND (
                       v.exit_time IS NULL
                       OR datetime(v.exit_time) > datetime('now', '-7 days')
                     )"""
        q += " ORDER BY COALESCE(v.entry_time, v.expected_at, v.created_at) DESC"
        rows = self.db.execute(q, params).fetchall()
        return [dict(r) for r in rows]

    def get(self, pid: int) -> Optional[dict]:
        row = self.db.execute(
            "SELECT * FROM rwa_visitor_passes WHERE id=? AND company_id=?",
            (pid, self.company_id),
        ).fetchone()
        return dict(row) if row else None

    def add(self, *, visitor_name: str, flat_id: Optional[int] = None,
            visitor_phone: str = "", vehicle_no: str = "",
            purpose: str = "GUEST",
            expected_at: Optional[str] = None,
            valid_until: Optional[str] = None,
            issued_by: str = "") -> dict:
        """Create a pass and return it (with the generated pass_code)."""
        visitor_name = (visitor_name or "").strip()
        if not visitor_name:
            raise ValueError("Visitor name is required.")
        purpose = (purpose or "GUEST").upper()
        if purpose not in VALID_PURPOSES:
            purpose = "OTHER"

        # Generate a unique 6-char pass code. UNIQUE collision is rare
        # but defensive: retry a handful.
        pass_code = None
        for _ in range(10):
            candidate = _generate_pass_code()
            dupe = self.db.execute(
                "SELECT 1 FROM rwa_visitor_passes "
                " WHERE company_id=? AND pass_code=?",
                (self.company_id, candidate),
            ).fetchone()
            if not dupe:
                pass_code = candidate
                break
        if pass_code is None:
            raise RuntimeError("Could not generate unique pass code.")

        cur = self.db.execute(
            """INSERT INTO rwa_visitor_passes
               (company_id, flat_id, visitor_name, visitor_phone,
                vehicle_no, purpose, expected_at, valid_until,
                pass_code, issued_by)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (self.company_id, flat_id, visitor_name,
             visitor_phone or None, vehicle_no or None,
             purpose, expected_at or None, valid_until or None,
             pass_code, issued_by or None),
        )
        self.db.commit()
        return self.get(cur.lastrowid)

    def update(self, pid: int, **kw) -> None:
        sets, params = [], []
        for k, v in kw.items():
            if k not in _EDITABLE:
                continue
            sets.append(f"{k}=?")
            params.append(v)
        if not sets:
            return
        params.extend([pid, self.company_id])
        self.db.execute(
            f"UPDATE rwa_visitor_passes SET {', '.join(sets)} "
            "WHERE id=? AND company_id=?",
            params,
        )
        self.db.commit()

    def mark_entered(self, pid: int) -> None:
        self.db.execute(
            "UPDATE rwa_visitor_passes SET entry_time=datetime('now') "
            "WHERE id=? AND company_id=?",
            (pid, self.company_id),
        )
        self.db.commit()

    def mark_exited(self, pid: int) -> None:
        self.db.execute(
            "UPDATE rwa_visitor_passes SET exit_time=datetime('now') "
            "WHERE id=? AND company_id=?",
            (pid, self.company_id),
        )
        self.db.commit()

    def delete(self, pid: int) -> None:
        self.db.execute(
            "DELETE FROM rwa_visitor_passes WHERE id=? AND company_id=?",
            (pid, self.company_id),
        )
        self.db.commit()
