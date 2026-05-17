"""
Tiny audit-log helper for page handlers.

Goal: a one-line ``page_audit(self, "add_flat", ...)`` call from any
RWAGenie page that does the right thing whether or not auth is wired
up. Pulls the current AuthSession off the top-level window (set by
RWAMainWindow), so pages don't need to take an `auth` constructor
arg.

If the page's top window has no `auth` (legacy callers, unit tests),
this is a silent no-op — never raises, never blocks the caller's
success path.
"""
from __future__ import annotations

from typing import Optional

from PySide6.QtWidgets import QWidget

from app.services.audit import AuditLogService
from app.services.auth  import AuthSession


def page_audit(page: QWidget,
               action: str,
               *,
               entity_type: str = "",
               entity_id: Optional[int] = None,
               summary: str = "",
               before: Optional[dict] = None,
               after: Optional[dict] = None) -> None:
    """Record one audit row. Looks up auth via page.window().auth.

    Pages keep their existing `(db, company_id, tree)` constructor;
    no new parameter to thread through. The trade-off is that pages
    must inherit from QWidget (they do) and must be added to a real
    top-level window before the call (they are, by the time a
    user-triggered action fires)."""
    win = page.window() if isinstance(page, QWidget) else None
    auth: Optional[AuthSession] = getattr(win, "auth", None)
    db = getattr(page, "db", None) or getattr(win, "db", None)
    cid = getattr(page, "company_id", None) or getattr(win, "company_id", None)
    if db is None or cid is None:
        return
    AuditLogService(db, cid).record(
        auth, action,
        entity_type=entity_type,
        entity_id=entity_id,
        summary=summary,
        before=before, after=after,
    )
