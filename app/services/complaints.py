"""
Complaint-tracking service — maintenance / civic tickets raised by
residents.
"""
from __future__ import annotations

from typing import Optional


VALID_CATEGORIES = (
    "PLUMBING", "ELECTRICAL", "NOISE", "SECURITY",
    "CIVIL", "HOUSEKEEPING", "GARDEN", "PARKING", "OTHER",
)
VALID_PRIORITIES = ("LOW", "NORMAL", "HIGH", "URGENT")
VALID_STATUSES   = ("OPEN", "IN_PROGRESS", "RESOLVED", "CLOSED")

_EDITABLE = {
    "flat_id", "raised_by_owner",
    "category", "title", "description",
    "priority", "status",
    "assigned_to", "resolution_notes",
    "resolved_at",
}


class ComplaintsService:
    def __init__(self, db, company_id: int):
        self.db = db
        self.company_id = company_id

    def list(self, status: Optional[str] = None) -> list[dict]:
        q = """SELECT c.id, c.flat_id, c.raised_by_owner, c.category,
                      c.title, c.description, c.priority, c.status,
                      c.assigned_to, c.resolution_notes,
                      c.raised_at, c.resolved_at,
                      f.flat_no, o.name AS raised_by_name
                 FROM rwa_complaints c
            LEFT JOIN rwa_flats f  ON f.id = c.flat_id
            LEFT JOIN rwa_owners o ON o.id = c.raised_by_owner
                WHERE c.company_id=?"""
        params: list = [self.company_id]
        if status:
            q += " AND c.status=?"
            params.append(status.upper())
        # Open and high-priority float to top, then by date desc.
        q += """ ORDER BY
                  CASE c.status WHEN 'OPEN' THEN 0
                                WHEN 'IN_PROGRESS' THEN 1
                                WHEN 'RESOLVED' THEN 2
                                ELSE 3 END,
                  CASE c.priority WHEN 'URGENT' THEN 0
                                  WHEN 'HIGH' THEN 1
                                  WHEN 'NORMAL' THEN 2
                                  ELSE 3 END,
                  c.raised_at DESC"""
        rows = self.db.execute(q, params).fetchall()
        return [dict(r) for r in rows]

    def get(self, complaint_id: int) -> Optional[dict]:
        row = self.db.execute(
            "SELECT * FROM rwa_complaints WHERE id=? AND company_id=?",
            (complaint_id, self.company_id),
        ).fetchone()
        return dict(row) if row else None

    def add(self, *, title: str, flat_id: Optional[int] = None,
            raised_by_owner: Optional[int] = None,
            category: str = "OTHER", description: str = "",
            priority: str = "NORMAL",
            assigned_to: str = "") -> int:
        title = (title or "").strip()
        if not title:
            raise ValueError("Title is required.")
        priority = priority.upper()
        if priority not in VALID_PRIORITIES:
            raise ValueError(
                f"priority must be one of {VALID_PRIORITIES}"
            )
        category = (category or "OTHER").upper()
        if category not in VALID_CATEGORIES:
            category = "OTHER"
        cur = self.db.execute(
            """INSERT INTO rwa_complaints
               (company_id, flat_id, raised_by_owner, category,
                title, description, priority, status, assigned_to)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            (self.company_id, flat_id, raised_by_owner, category,
             title, description or "", priority, "OPEN",
             assigned_to or None),
        )
        self.db.commit()
        return cur.lastrowid

    def update(self, complaint_id: int, **kw) -> None:
        # Sanitise enums if present
        if "priority" in kw and kw["priority"]:
            kw["priority"] = kw["priority"].upper()
            if kw["priority"] not in VALID_PRIORITIES:
                raise ValueError(
                    f"priority must be one of {VALID_PRIORITIES}"
                )
        if "status" in kw and kw["status"]:
            kw["status"] = kw["status"].upper()
            if kw["status"] not in VALID_STATUSES:
                raise ValueError(
                    f"status must be one of {VALID_STATUSES}"
                )
        if "category" in kw and kw["category"]:
            kw["category"] = kw["category"].upper()

        # Auto-stamp resolved_at when status flips to RESOLVED
        if kw.get("status") == "RESOLVED":
            kw.setdefault("resolved_at",
                          self.db.execute("SELECT datetime('now') AS t")
                              .fetchone()["t"])
        elif kw.get("status") in ("OPEN", "IN_PROGRESS"):
            kw["resolved_at"] = None

        sets, params = [], []
        for k, v in kw.items():
            if k not in _EDITABLE:
                continue
            sets.append(f"{k}=?")
            params.append(v)
        if not sets:
            return
        params.extend([complaint_id, self.company_id])
        self.db.execute(
            f"UPDATE rwa_complaints SET {', '.join(sets)} "
            "WHERE id=? AND company_id=?",
            params,
        )
        self.db.commit()

    def delete(self, complaint_id: int) -> None:
        self.db.execute(
            "DELETE FROM rwa_complaints WHERE id=? AND company_id=?",
            (complaint_id, self.company_id),
        )
        self.db.commit()

    def stats(self) -> dict:
        """Quick counters for the page header."""
        row = self.db.execute(
            """SELECT
                 SUM(CASE WHEN status='OPEN'         THEN 1 ELSE 0 END) AS open,
                 SUM(CASE WHEN status='IN_PROGRESS'  THEN 1 ELSE 0 END) AS in_progress,
                 SUM(CASE WHEN status='RESOLVED'     THEN 1 ELSE 0 END) AS resolved,
                 SUM(CASE WHEN priority='URGENT' AND status != 'CLOSED' THEN 1 ELSE 0 END) AS urgent_open
               FROM rwa_complaints
              WHERE company_id=?""",
            (self.company_id,),
        ).fetchone()
        return {
            "open":         row["open"] or 0,
            "in_progress":  row["in_progress"] or 0,
            "resolved":     row["resolved"] or 0,
            "urgent_open":  row["urgent_open"] or 0,
        }
