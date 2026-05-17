"""
Append-only audit log.

Page handlers call ``audit.record(...)`` after the underlying service
call succeeds. The log is never edited or deleted from inside the
app — it's the historical record of who changed what.

Design notes:
  • Logging happens at the PAGE layer, not inside the domain services.
    Pushing it into FlatsService / OwnersService etc. would have meant
    every service grows an auth dependency and a 'who is calling me'
    param. Keeping it at the page means the page knows the user (via
    parent.auth) and the page knows the user-visible action label.
  • before/after JSON snapshots are optional. Pages that want a real
    diff trail pass them; trivial actions ("send_broadcast") can
    skip them and just record a summary.
  • The 'username' column is denormalised on purpose — a deleted
    user's name still shows up in old log rows.
"""
from __future__ import annotations

import json
import logging
from typing import Any, Optional

from app.services.auth import AuthSession


logger = logging.getLogger(__name__)


class AuditLogService:
    def __init__(self, db, company_id: int):
        self.db = db
        self.company_id = company_id

    # ── Recording ──────────────────────────────────────────────────────

    def record(self,
               session: Optional[AuthSession],
               action: str,
               *,
               entity_type: str = "",
               entity_id: Optional[int] = None,
               summary: str = "",
               before: Optional[dict] = None,
               after: Optional[dict] = None) -> None:
        """Write one audit row. Never raises — logging an audit is
        secondary to whatever business action just succeeded; we don't
        want a logging bug to undo a save."""
        try:
            self.db.execute(
                """INSERT INTO rwa_audit_log
                   (company_id, user_id, username, action,
                    entity_type, entity_id, summary,
                    before_json, after_json)
                   VALUES (?,?,?,?,?,?,?,?,?)""",
                (
                    self.company_id,
                    session.user_id if session else None,
                    session.username if session else "",
                    action,
                    entity_type or "",
                    entity_id,
                    summary or "",
                    _jsonify(before),
                    _jsonify(after),
                ),
            )
            self.db.commit()
        except Exception:
            logger.exception("Failed to record audit log entry (action=%s)",
                             action)

    # ── Reading ────────────────────────────────────────────────────────

    def list(self, *,
             limit: int = 500,
             action_substr: str = "",
             username: str = "",
             entity_type: str = "",
             since: str = "") -> list[dict]:
        """Most-recent first, with simple LIKE/EQ filters. Pass
        empty strings to skip a filter."""
        sql = """SELECT id, user_id, username, action,
                        entity_type, entity_id, summary, at
                   FROM rwa_audit_log
                  WHERE company_id=?"""
        params: list[Any] = [self.company_id]
        if action_substr:
            sql += " AND action LIKE ?"
            params.append(f"%{action_substr}%")
        if username:
            sql += " AND username = ?"
            params.append(username)
        if entity_type:
            sql += " AND entity_type = ?"
            params.append(entity_type)
        if since:
            sql += " AND at >= ?"
            params.append(since)
        sql += " ORDER BY at DESC, id DESC LIMIT ?"
        params.append(int(limit))
        rows = self.db.execute(sql, params).fetchall()
        return [dict(r) for r in rows]

    def detail(self, log_id: int) -> Optional[dict]:
        row = self.db.execute(
            "SELECT * FROM rwa_audit_log WHERE id=? AND company_id=?",
            (log_id, self.company_id),
        ).fetchone()
        return dict(row) if row else None

    def distinct_users(self) -> list[str]:
        rows = self.db.execute(
            "SELECT DISTINCT username FROM rwa_audit_log "
            "WHERE company_id=? AND username<>'' ORDER BY username",
            (self.company_id,),
        ).fetchall()
        return [r["username"] for r in rows]


def _jsonify(d: Optional[dict]) -> Optional[str]:
    if d is None:
        return None
    try:
        # default=str so date / Decimal / Path values don't blow up
        return json.dumps(d, ensure_ascii=False, default=str)
    except Exception:
        return json.dumps({"_unserialisable": True})
