"""
Broadcasts service — society-wide messages.

For v0.1 we persist the message + intended audience. Actual delivery
(email / SMS / WhatsApp) is wired separately once the provider is
chosen. Calling send() marks sent_at + sent_count from the resolved
audience size so admins see what would go out.
"""
from __future__ import annotations

from typing import Optional


VALID_CHANNELS = ("NONE", "EMAIL", "SMS", "WHATSAPP")
VALID_AUDIENCES = ("ALL", "OWNERS", "TENANTS", "OUTSTANDING", "SELECTED")

_EDITABLE = {
    "subject", "body", "channel", "audience", "selected_flats",
    "sent_at", "sent_count",
}


class BroadcastsService:
    def __init__(self, db, company_id: int):
        self.db = db
        self.company_id = company_id

    def list(self) -> list[dict]:
        rows = self.db.execute(
            """SELECT id, subject, body, channel, audience, selected_flats,
                      sent_at, sent_count, created_at
                 FROM rwa_broadcasts
                WHERE company_id=?
             ORDER BY COALESCE(sent_at, created_at) DESC""",
            (self.company_id,),
        ).fetchall()
        return [dict(r) for r in rows]

    def get(self, bid: int) -> Optional[dict]:
        row = self.db.execute(
            "SELECT * FROM rwa_broadcasts WHERE id=? AND company_id=?",
            (bid, self.company_id),
        ).fetchone()
        return dict(row) if row else None

    def add(self, *, subject: str, body: str = "",
            channel: str = "NONE",
            audience: str = "ALL",
            selected_flats: Optional[str] = None) -> int:
        subject = (subject or "").strip()
        if not subject:
            raise ValueError("Subject is required.")
        channel = (channel or "NONE").upper()
        if channel not in VALID_CHANNELS:
            raise ValueError(f"channel must be one of {VALID_CHANNELS}")
        audience = (audience or "ALL").upper()
        if audience not in VALID_AUDIENCES:
            raise ValueError(f"audience must be one of {VALID_AUDIENCES}")

        cur = self.db.execute(
            """INSERT INTO rwa_broadcasts
               (company_id, subject, body, channel, audience, selected_flats)
               VALUES (?,?,?,?,?,?)""",
            (self.company_id, subject, body or "", channel, audience,
             selected_flats or None),
        )
        self.db.commit()
        return cur.lastrowid

    def update(self, bid: int, **kw) -> None:
        sets, params = [], []
        for k, v in kw.items():
            if k not in _EDITABLE:
                continue
            sets.append(f"{k}=?")
            params.append(v)
        if not sets:
            return
        params.extend([bid, self.company_id])
        self.db.execute(
            f"UPDATE rwa_broadcasts SET {', '.join(sets)} "
            "WHERE id=? AND company_id=?",
            params,
        )
        self.db.commit()

    def delete(self, bid: int) -> None:
        self.db.execute(
            "DELETE FROM rwa_broadcasts WHERE id=? AND company_id=?",
            (bid, self.company_id),
        )
        self.db.commit()

    def resolve_audience_count(self, audience: str,
                                selected_flats: Optional[str] = None) -> int:
        """Estimate how many recipients a broadcast would hit. Used for
        the 'Mark as sent' button to seed sent_count, and for the
        composer preview."""
        audience = (audience or "ALL").upper()
        cid = self.company_id
        if audience == "ALL":
            r = self.db.execute(
                """SELECT COUNT(DISTINCT o.id) AS n
                     FROM rwa_owners o
                     JOIN rwa_flat_owners fo ON fo.owner_id = o.id
                     JOIN rwa_flats f ON f.id = fo.flat_id
                    WHERE o.company_id=? AND o.active=1 AND f.active=1""",
                (cid,),
            ).fetchone()
            return r["n"] or 0
        if audience == "OWNERS":
            r = self.db.execute(
                """SELECT COUNT(DISTINCT o.id) AS n
                     FROM rwa_owners o
                     JOIN rwa_flat_owners fo ON fo.owner_id = o.id AND fo.role='OWNER'
                     JOIN rwa_flats f ON f.id = fo.flat_id
                    WHERE o.company_id=? AND o.active=1 AND f.active=1""",
                (cid,),
            ).fetchone()
            return r["n"] or 0
        if audience == "TENANTS":
            r = self.db.execute(
                """SELECT COUNT(DISTINCT o.id) AS n
                     FROM rwa_owners o
                     JOIN rwa_flat_owners fo ON fo.owner_id = o.id AND fo.role='TENANT'
                     JOIN rwa_flats f ON f.id = fo.flat_id
                    WHERE o.company_id=? AND o.active=1 AND f.active=1""",
                (cid,),
            ).fetchone()
            return r["n"] or 0
        if audience == "OUTSTANDING":
            # Approximation for v0.1: count primary owners of all flats
            # whose ledger has Dr balance > 0. Refined when bills/dues
            # tables ship.
            return 0   # TODO: tie to FlatsService.outstanding_balance_for_flats
        if audience == "SELECTED" and selected_flats:
            ids = [int(x) for x in selected_flats.split(",") if x.strip().isdigit()]
            if not ids:
                return 0
            placeholders = ",".join("?" * len(ids))
            r = self.db.execute(
                f"""SELECT COUNT(DISTINCT o.id) AS n
                      FROM rwa_owners o
                      JOIN rwa_flat_owners fo ON fo.owner_id = o.id
                     WHERE fo.flat_id IN ({placeholders})
                       AND o.company_id=? AND o.active=1""",
                (*ids, cid),
            ).fetchone()
            return r["n"] or 0
        return 0
