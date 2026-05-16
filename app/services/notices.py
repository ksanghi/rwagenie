"""
Notice-board service — society-wide announcements.

CRUD on rwa_notices. Pinned notices float to the top; expired notices
(expires_on < today) are hidden from default lists but kept in DB.
"""
from __future__ import annotations

from typing import Optional


_EDITABLE = {"title", "body", "posted_by", "pinned", "expires_on"}


class NoticesService:
    def __init__(self, db, company_id: int):
        self.db = db
        self.company_id = company_id

    def list(self, include_expired: bool = False) -> list[dict]:
        q = """SELECT id, title, body, posted_by, pinned, expires_on, created_at
                 FROM rwa_notices
                WHERE company_id = ?"""
        if not include_expired:
            q += " AND (expires_on IS NULL OR expires_on >= date('now'))"
        q += " ORDER BY pinned DESC, created_at DESC"
        rows = self.db.execute(q, (self.company_id,)).fetchall()
        return [dict(r) for r in rows]

    def get(self, notice_id: int) -> Optional[dict]:
        row = self.db.execute(
            "SELECT * FROM rwa_notices WHERE id=? AND company_id=?",
            (notice_id, self.company_id),
        ).fetchone()
        return dict(row) if row else None

    def add(self, *, title: str, body: str = "", posted_by: str = "",
            pinned: bool = False, expires_on: Optional[str] = None) -> int:
        title = (title or "").strip()
        if not title:
            raise ValueError("Title is required.")
        cur = self.db.execute(
            """INSERT INTO rwa_notices
               (company_id, title, body, posted_by, pinned, expires_on)
               VALUES (?,?,?,?,?,?)""",
            (self.company_id, title, body or "", posted_by or None,
             int(bool(pinned)), expires_on or None),
        )
        self.db.commit()
        return cur.lastrowid

    def update(self, notice_id: int, **kw) -> None:
        if not kw:
            return
        sets, params = [], []
        for k, v in kw.items():
            if k not in _EDITABLE:
                continue
            if k == "pinned":
                v = int(bool(v))
            sets.append(f"{k}=?")
            params.append(v)
        if not sets:
            return
        params.extend([notice_id, self.company_id])
        self.db.execute(
            f"UPDATE rwa_notices SET {', '.join(sets)} "
            "WHERE id=? AND company_id=?",
            params,
        )
        self.db.commit()

    def delete(self, notice_id: int) -> None:
        # Hard delete — notices are ephemeral, no ledger linkage.
        self.db.execute(
            "DELETE FROM rwa_notices WHERE id=? AND company_id=?",
            (notice_id, self.company_id),
        )
        self.db.commit()
