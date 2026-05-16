"""
Polls service — society votes (AGM resolutions, amenity decisions).

A poll has a title, optional description, a list of options stored as
JSON, optional open/close timestamps, and a one-vote-per setting
(FLAT or OWNER). Votes live in rwa_poll_votes; the UNIQUE constraint
there guards against duplicate voting.
"""
from __future__ import annotations

import json
from typing import Optional


VALID_STATUS = ("DRAFT", "OPEN", "CLOSED", "ARCHIVED")
VALID_VOTE_PER = ("FLAT", "OWNER")

_EDITABLE = {
    "title", "description", "options_json",
    "opens_at", "closes_at", "one_vote_per", "status",
}


class PollsService:
    def __init__(self, db, company_id: int):
        self.db = db
        self.company_id = company_id

    def list(self, status: Optional[str] = None) -> list[dict]:
        q = """SELECT id, title, description, options_json,
                      opens_at, closes_at, one_vote_per, status, created_at
                 FROM rwa_polls
                WHERE company_id=?"""
        params: list = [self.company_id]
        if status:
            q += " AND status=?"
            params.append(status.upper())
        q += """ ORDER BY
                   CASE status WHEN 'OPEN' THEN 0
                               WHEN 'DRAFT' THEN 1
                               WHEN 'CLOSED' THEN 2
                               ELSE 3 END,
                   created_at DESC"""
        rows = self.db.execute(q, params).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            try:
                d["options"] = json.loads(d.get("options_json") or "[]")
            except Exception:
                d["options"] = []
            d["vote_count"] = self._count_votes(d["id"])
            out.append(d)
        return out

    def get(self, pid: int) -> Optional[dict]:
        row = self.db.execute(
            "SELECT * FROM rwa_polls WHERE id=? AND company_id=?",
            (pid, self.company_id),
        ).fetchone()
        if not row:
            return None
        d = dict(row)
        try:
            d["options"] = json.loads(d.get("options_json") or "[]")
        except Exception:
            d["options"] = []
        d["tally"] = self._tally(pid, len(d["options"]))
        return d

    def add(self, *, title: str, options: list[str],
            description: str = "",
            opens_at: Optional[str] = None,
            closes_at: Optional[str] = None,
            one_vote_per: str = "FLAT",
            status: str = "DRAFT") -> int:
        title = (title or "").strip()
        if not title:
            raise ValueError("Title is required.")
        options = [str(o).strip() for o in (options or []) if str(o).strip()]
        if len(options) < 2:
            raise ValueError(
                "A poll needs at least two options."
            )
        one_vote_per = (one_vote_per or "FLAT").upper()
        if one_vote_per not in VALID_VOTE_PER:
            raise ValueError(f"one_vote_per must be {VALID_VOTE_PER}")
        status = (status or "DRAFT").upper()
        if status not in VALID_STATUS:
            raise ValueError(f"status must be one of {VALID_STATUS}")
        cur = self.db.execute(
            """INSERT INTO rwa_polls
               (company_id, title, description, options_json,
                opens_at, closes_at, one_vote_per, status)
               VALUES (?,?,?,?,?,?,?,?)""",
            (self.company_id, title, description or "",
             json.dumps(options),
             opens_at or None, closes_at or None,
             one_vote_per, status),
        )
        self.db.commit()
        return cur.lastrowid

    def update(self, pid: int, *, options: Optional[list[str]] = None,
                **kw) -> None:
        if options is not None:
            options = [str(o).strip() for o in options if str(o).strip()]
            if len(options) < 2:
                raise ValueError(
                    "A poll needs at least two options."
                )
            kw["options_json"] = json.dumps(options)
        if "status" in kw and kw["status"]:
            kw["status"] = kw["status"].upper()
            if kw["status"] not in VALID_STATUS:
                raise ValueError(f"status must be one of {VALID_STATUS}")
        if "one_vote_per" in kw and kw["one_vote_per"]:
            kw["one_vote_per"] = kw["one_vote_per"].upper()
            if kw["one_vote_per"] not in VALID_VOTE_PER:
                raise ValueError(f"one_vote_per must be {VALID_VOTE_PER}")
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
            f"UPDATE rwa_polls SET {', '.join(sets)} "
            "WHERE id=? AND company_id=?",
            params,
        )
        self.db.commit()

    def delete(self, pid: int) -> None:
        # ON DELETE CASCADE drops votes too via the schema.
        self.db.execute(
            "DELETE FROM rwa_polls WHERE id=? AND company_id=?",
            (pid, self.company_id),
        )
        self.db.commit()

    def cast_vote(self, poll_id: int, option_index: int, *,
                   flat_id: Optional[int] = None,
                   owner_id: Optional[int] = None) -> int:
        """Record one vote. Caller must pass flat_id when one_vote_per=FLAT,
        owner_id when =OWNER. Raises ValueError on duplicate."""
        try:
            cur = self.db.execute(
                """INSERT INTO rwa_poll_votes
                   (poll_id, flat_id, owner_id, option_index)
                   VALUES (?,?,?,?)""",
                (poll_id, flat_id, owner_id, int(option_index)),
            )
        except Exception as e:
            raise ValueError(
                "That flat / owner has already voted on this poll."
            ) from e
        self.db.commit()
        return cur.lastrowid

    # ── Internals ────────────────────────────────────────────────────

    def _count_votes(self, poll_id: int) -> int:
        r = self.db.execute(
            "SELECT COUNT(*) AS n FROM rwa_poll_votes WHERE poll_id=?",
            (poll_id,),
        ).fetchone()
        return r["n"] or 0

    def _tally(self, poll_id: int, n_options: int) -> list[int]:
        """Return [count_for_option_0, count_for_option_1, …]"""
        rows = self.db.execute(
            "SELECT option_index, COUNT(*) AS n FROM rwa_poll_votes "
            " WHERE poll_id=? GROUP BY option_index",
            (poll_id,),
        ).fetchall()
        out = [0] * max(n_options, 0)
        for r in rows:
            i = int(r["option_index"])
            if 0 <= i < len(out):
                out[i] = r["n"] or 0
        return out
