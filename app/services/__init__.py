"""
RWA domain services — sit between the UI and the SQLite tables.

Pure-Python; no Qt. Used by the verticals/rwa/pages/ widgets.
"""
from __future__ import annotations

from typing import Optional


_SUNDRY_DEBTORS = "Sundry Debtors"   # default group for per-flat ledgers


class FlatsService:
    """CRUD for rwa_flats + auto-managed companion ledgers."""

    def __init__(self, db, company_id: int, tree):
        self.db = db
        self.company_id = company_id
        self.tree = tree

    # ── Read ──────────────────────────────────────────────────────────────────

    def list_flats(self, active_only: bool = True) -> list[dict]:
        q = """SELECT f.id, f.flat_no, f.block, f.tower, f.floor,
                      f.area_sqft, f.ownership_type, f.ledger_id,
                      f.move_in_date, f.notes, f.active,
                      l.name AS ledger_name,
                      (SELECT COUNT(*) FROM rwa_flat_owners fo WHERE fo.flat_id=f.id)
                        AS owner_count,
                      (SELECT o.name FROM rwa_flat_owners fo
                          JOIN rwa_owners o ON o.id = fo.owner_id
                         WHERE fo.flat_id=f.id AND fo.is_primary=1
                         LIMIT 1)
                        AS primary_owner
                 FROM rwa_flats f
            LEFT JOIN ledgers l ON l.id = f.ledger_id
                WHERE f.company_id=? """
        params: list = [self.company_id]
        if active_only:
            q += " AND f.active=1"
        q += " ORDER BY f.flat_no"
        rows = self.db.execute(q, params).fetchall()
        return [dict(r) for r in rows]

    def get_flat(self, flat_id: int) -> Optional[dict]:
        row = self.db.execute(
            "SELECT * FROM rwa_flats WHERE id=? AND company_id=?",
            (flat_id, self.company_id),
        ).fetchone()
        return dict(row) if row else None

    # ── Write ─────────────────────────────────────────────────────────────────

    def add_flat(
        self,
        flat_no: str,
        block: str = "",
        tower: str = "",
        floor: str = "",
        area_sqft: Optional[float] = None,
        ownership_type: str = "OWNED",
        move_in_date: Optional[str] = None,
        notes: str = "",
    ) -> int:
        flat_no = (flat_no or "").strip()
        if not flat_no:
            raise ValueError("Flat number is required.")

        # Reject duplicates explicitly so the UI can show a friendly error.
        dupe = self.db.execute(
            "SELECT id FROM rwa_flats WHERE company_id=? AND flat_no=?",
            (self.company_id, flat_no),
        ).fetchone()
        if dupe:
            raise ValueError(f"Flat '{flat_no}' already exists.")

        # Auto-create the Sundry Debtor ledger. If a ledger by the same
        # name happens to already exist (e.g. from migration), reuse it
        # instead of creating a duplicate.
        ledger_name = f"Flat {flat_no}"
        existing_ledger = self.db.execute(
            "SELECT id FROM ledgers WHERE company_id=? AND name=?",
            (self.company_id, ledger_name),
        ).fetchone()
        if existing_ledger:
            ledger_id = existing_ledger["id"]
        else:
            ledger_id = self.tree.add_ledger(
                name=ledger_name, group_name=_SUNDRY_DEBTORS,
            )

        cur = self.db.execute(
            """INSERT INTO rwa_flats
               (company_id, flat_no, block, tower, floor, area_sqft,
                ownership_type, ledger_id, move_in_date, notes)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (self.company_id, flat_no, block or None, tower or None,
             floor or None, area_sqft, ownership_type or "OWNED",
             ledger_id, move_in_date or None, notes or None),
        )
        self.db.commit()
        return cur.lastrowid

    def update_flat(self, flat_id: int, **kwargs) -> None:
        existing = self.get_flat(flat_id)
        if not existing:
            raise ValueError("Flat not found.")

        # If flat_no is being changed, rename the companion ledger too —
        # only if the ledger has no transactions yet (otherwise the rename
        # would surprise the user looking at past Day Book entries).
        new_flat_no = (kwargs.get("flat_no") or existing["flat_no"]).strip()
        if new_flat_no != existing["flat_no"]:
            if existing.get("ledger_id"):
                vouchered = self.db.execute(
                    "SELECT COUNT(*) AS c FROM voucher_lines WHERE ledger_id=?",
                    (existing["ledger_id"],),
                ).fetchone()
                if (vouchered["c"] or 0) > 0:
                    raise ValueError(
                        "Cannot rename a flat whose ledger already has "
                        "transactions — would change historical references. "
                        "Create a new flat and deactivate the old one instead."
                    )
                self.tree.update_ledger(
                    existing["ledger_id"], name=f"Flat {new_flat_no}",
                )

        # Whitelist fields to avoid SQL injection via key.
        editable = {
            "flat_no", "block", "tower", "floor", "area_sqft",
            "ownership_type", "move_in_date", "notes", "active",
        }
        sets, params = [], []
        for k, v in kwargs.items():
            if k not in editable:
                continue
            if k == "active":
                v = int(bool(v))
            sets.append(f"{k}=?")
            params.append(v)
        if not sets:
            return
        params.extend([flat_id, self.company_id])
        self.db.execute(
            f"UPDATE rwa_flats SET {', '.join(sets)} "
            "WHERE id=? AND company_id=?",
            params,
        )
        self.db.commit()

    def deactivate_flat(self, flat_id: int) -> None:
        """Soft-delete. Keeps the ledger and history intact. Use this
        rather than a hard delete — the flat's voucher history would
        be orphaned otherwise."""
        self.update_flat(flat_id, active=0)

    def reactivate_flat(self, flat_id: int) -> None:
        self.update_flat(flat_id, active=1)

    # ── Owner assignments ────────────────────────────────────────────────────

    def owners_for_flat(self, flat_id: int) -> list[dict]:
        rows = self.db.execute(
            """SELECT fo.id AS link_id, fo.role, fo.is_primary, fo.since_date,
                      o.id AS owner_id, o.name, o.primary_phone, o.email
                 FROM rwa_flat_owners fo
                 JOIN rwa_owners o ON o.id = fo.owner_id
                WHERE fo.flat_id = ?
             ORDER BY fo.is_primary DESC, o.name""",
            (flat_id,),
        ).fetchall()
        return [dict(r) for r in rows]

    def assign_owner(
        self,
        flat_id: int, owner_id: int,
        role: str = "OWNER", is_primary: bool = False,
        since_date: Optional[str] = None,
    ) -> int:
        # If marking as primary, clear other primaries on this flat first.
        if is_primary:
            self.db.execute(
                "UPDATE rwa_flat_owners SET is_primary=0 WHERE flat_id=?",
                (flat_id,),
            )
        try:
            cur = self.db.execute(
                """INSERT INTO rwa_flat_owners
                   (flat_id, owner_id, role, is_primary, since_date)
                   VALUES (?,?,?,?,?)""",
                (flat_id, owner_id, role.upper(), int(bool(is_primary)),
                 since_date),
            )
        except Exception as e:
            # UNIQUE(flat_id, owner_id, role) — re-raise with friendly text.
            raise ValueError(
                "This person is already assigned to this flat in that role."
            ) from e
        self.db.commit()
        return cur.lastrowid

    def unassign_owner(self, link_id: int) -> None:
        self.db.execute(
            "DELETE FROM rwa_flat_owners WHERE id=?", (link_id,),
        )
        self.db.commit()


class OwnersService:
    """CRUD for rwa_owners (the member directory)."""

    def __init__(self, db, company_id: int):
        self.db = db
        self.company_id = company_id

    def list_owners(self, active_only: bool = True) -> list[dict]:
        q = """SELECT o.id, o.name, o.primary_phone, o.email,
                      o.kyc_id_type, o.kyc_id_number,
                      o.alternate_phone, o.emergency_name, o.emergency_phone,
                      o.notes, o.photo_path, o.active,
                      (SELECT COUNT(*) FROM rwa_flat_owners fo
                          JOIN rwa_flats f ON f.id = fo.flat_id
                         WHERE fo.owner_id = o.id AND f.active = 1)
                        AS flat_count,
                      (SELECT GROUP_CONCAT(f.flat_no, ', ')
                         FROM rwa_flat_owners fo
                         JOIN rwa_flats f ON f.id = fo.flat_id
                        WHERE fo.owner_id = o.id AND f.active = 1)
                        AS flats_csv
                 FROM rwa_owners o
                WHERE o.company_id = ?"""
        params: list = [self.company_id]
        if active_only:
            q += " AND o.active = 1"
        q += " ORDER BY o.name"
        rows = self.db.execute(q, params).fetchall()
        return [dict(r) for r in rows]

    def get_owner(self, owner_id: int) -> Optional[dict]:
        row = self.db.execute(
            "SELECT * FROM rwa_owners WHERE id=? AND company_id=?",
            (owner_id, self.company_id),
        ).fetchone()
        return dict(row) if row else None

    def add_owner(self, **kwargs) -> int:
        name = (kwargs.get("name") or "").strip()
        if not name:
            raise ValueError("Owner name is required.")
        cur = self.db.execute(
            """INSERT INTO rwa_owners
               (company_id, name, primary_phone, alternate_phone, email,
                kyc_id_type, kyc_id_number, photo_path,
                emergency_name, emergency_phone, notes)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (
                self.company_id, name,
                (kwargs.get("primary_phone") or None),
                (kwargs.get("alternate_phone") or None),
                (kwargs.get("email") or None),
                (kwargs.get("kyc_id_type") or None),
                (kwargs.get("kyc_id_number") or None),
                (kwargs.get("photo_path") or None),
                (kwargs.get("emergency_name") or None),
                (kwargs.get("emergency_phone") or None),
                (kwargs.get("notes") or None),
            ),
        )
        self.db.commit()
        return cur.lastrowid

    def update_owner(self, owner_id: int, **kwargs) -> None:
        editable = {
            "name", "primary_phone", "alternate_phone", "email",
            "kyc_id_type", "kyc_id_number", "photo_path",
            "emergency_name", "emergency_phone", "notes", "active",
        }
        sets, params = [], []
        for k, v in kwargs.items():
            if k not in editable:
                continue
            if k == "active":
                v = int(bool(v))
            sets.append(f"{k}=?")
            params.append(v)
        if not sets:
            return
        params.extend([owner_id, self.company_id])
        self.db.execute(
            f"UPDATE rwa_owners SET {', '.join(sets)} "
            "WHERE id=? AND company_id=?",
            params,
        )
        self.db.commit()

    def deactivate_owner(self, owner_id: int) -> None:
        self.update_owner(owner_id, active=0)
