"""
RWA domain services — sit between the UI and the SQLite tables.

Pure-Python; no Qt. Used by the app.pages.* widgets.

Public types:
  FlatsService  — CRUD for flats, primary-owner/tenant pointers,
                  bill-payer resolution, current outstanding balance.
  OwnersService — CRUD for people (members + tenants), including
                  payment-method details.

The 'triangle' (flat ↔ owner ↔ tenant) is stored two ways:
  - rwa_flat_owners is the authoritative many-to-many (full history,
    joint ownership, multiple tenants over time)
  - rwa_flats.primary_owner_id + primary_tenant_id are denormalised
    'currently who' pointers for fast Flats-page rendering. Kept in
    sync by set_primary_owner / set_primary_tenant.
"""
from __future__ import annotations

from typing import Optional


_SUNDRY_DEBTORS = "Sundry Debtors"   # default group for per-flat ledgers


# Whitelists of columns each service is allowed to UPDATE. Keeping these
# at module level so they're easy to audit when new fields are added.
_FLAT_EDITABLE = {
    "flat_no", "block", "tower", "floor", "flat_type",
    "area_sqft", "built_up_area_sqft", "parking_count", "storage_no",
    "ownership_type", "occupation_status",
    "primary_owner_id", "primary_tenant_id", "bill_payer",
    "sale_deed_date", "possession_date", "move_in_date",
    "notes", "active",
}

_OWNER_EDITABLE = {
    "name", "primary_phone", "alternate_phone", "email",
    "pan", "aadhaar_last4",
    "kyc_id_type", "kyc_id_number",
    "photo_path", "correspondence_address", "is_resident",
    "emergency_name", "emergency_phone",
    "preferred_payment_mode", "upi_id",
    "bank_account_no", "bank_ifsc", "bank_account_holder_name",
    "nach_mandate_ref",
    "notes", "active",
}

_LINK_EDITABLE = {
    "role", "is_primary", "since_date",
    "tenancy_from", "tenancy_to",
    "police_verification_ref", "police_verification_date",
    "monthly_rent", "security_deposit", "lease_doc_path",
}

VALID_OCCUPATION = ("OWNER_OCCUPIED", "RENTED", "VACANT")
VALID_BILL_PAYER = ("OWNER", "TENANT")
VALID_PAYMENT_MODES = ("UPI", "NACH", "TRANSFER", "CHEQUE", "CASH")
VALID_LINK_ROLES = ("OWNER", "TENANT", "FAMILY")


# ─────────────────────────────────────────────────────────────────────
# FlatsService
# ─────────────────────────────────────────────────────────────────────

class FlatsService:
    """CRUD for rwa_flats + auto-managed companion ledgers."""

    def __init__(self, db, company_id: int, tree):
        self.db = db
        self.company_id = company_id
        self.tree = tree

    # ── Read ──────────────────────────────────────────────────────────

    def list_flats(self, active_only: bool = True) -> list[dict]:
        """List view for the Flats page. Includes denormalised primary
        owner + primary tenant names so the table can render without
        extra queries per row."""
        q = """SELECT f.id, f.flat_no, f.block, f.tower, f.floor,
                      f.flat_type, f.area_sqft, f.built_up_area_sqft,
                      f.parking_count, f.storage_no,
                      f.ownership_type, f.occupation_status,
                      f.bill_payer, f.primary_owner_id, f.primary_tenant_id,
                      f.sale_deed_date, f.possession_date,
                      f.ledger_id, f.move_in_date, f.notes, f.active,
                      l.name AS ledger_name,
                      (SELECT o.name FROM rwa_owners o
                          WHERE o.id = f.primary_owner_id) AS primary_owner_name,
                      (SELECT o.name FROM rwa_owners o
                          WHERE o.id = f.primary_tenant_id) AS primary_tenant_name,
                      (SELECT COUNT(*) FROM rwa_flat_owners fo
                          WHERE fo.flat_id=f.id) AS owner_count
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

    def outstanding_balance_for_flats(
        self, flat_ids: Optional[list[int]] = None,
    ) -> dict[int, dict]:
        """
        Return {flat_id: {balance, type}} computed from the flat's
        companion ledger. Single SQL — no N+1 even at 1000+ flats.

        Mirrors AG's AccountTree.get_all_ledger_balances() but restricted
        to ledger ids referenced by rwa_flats. Caller may filter by
        passing a specific flat_ids list; otherwise every active flat
        for the company is included.
        """
        # Resolve the relevant ledger ids first.
        if flat_ids is None:
            id_rows = self.db.execute(
                "SELECT id, ledger_id FROM rwa_flats "
                " WHERE company_id=? AND active=1 AND ledger_id IS NOT NULL",
                (self.company_id,),
            ).fetchall()
        else:
            if not flat_ids:
                return {}
            placeholders = ",".join("?" * len(flat_ids))
            id_rows = self.db.execute(
                f"SELECT id, ledger_id FROM rwa_flats "
                f" WHERE company_id=? AND ledger_id IS NOT NULL "
                f"   AND id IN ({placeholders})",
                (self.company_id, *flat_ids),
            ).fetchall()

        ledger_to_flat = {r["ledger_id"]: r["id"] for r in id_rows}
        if not ledger_to_flat:
            return {}

        placeholders = ",".join("?" * len(ledger_to_flat))
        bal_rows = self.db.execute(
            f"""SELECT l.id AS ledger_id,
                       l.opening_balance, l.opening_type,
                       COALESCE(SUM(
                         CASE WHEN v.is_cancelled = 0
                              THEN vl.dr_amount ELSE 0 END
                       ), 0) AS total_dr,
                       COALESCE(SUM(
                         CASE WHEN v.is_cancelled = 0
                              THEN vl.cr_amount ELSE 0 END
                       ), 0) AS total_cr
                  FROM ledgers l
             LEFT JOIN voucher_lines vl ON vl.ledger_id  = l.id
             LEFT JOIN vouchers      v  ON vl.voucher_id = v.id
                 WHERE l.id IN ({placeholders})
              GROUP BY l.id""",
            list(ledger_to_flat.keys()),
        ).fetchall()

        out: dict[int, dict] = {}
        for r in bal_rows:
            ob       = r["opening_balance"] or 0.0
            ob_type  = r["opening_type"] or "Dr"
            net_ob   = ob if ob_type == "Dr" else -ob
            net      = net_ob + (r["total_dr"] or 0.0) - (r["total_cr"] or 0.0)
            out[ledger_to_flat[r["ledger_id"]]] = {
                "balance": abs(net),
                "type":    "Dr" if net >= 0 else "Cr",
            }
        return out

    def bill_payer_for_flat(self, flat_id: int) -> Optional[dict]:
        """
        Resolve which owner the maintenance bill chases for this flat.
        Returns the rwa_owners row (or None if not configured).
        """
        f = self.get_flat(flat_id)
        if not f:
            return None
        bp = (f.get("bill_payer") or "OWNER").upper()
        target_id = (
            f.get("primary_tenant_id") if bp == "TENANT"
            else f.get("primary_owner_id")
        )
        if not target_id:
            # Fallback: primary owner from the link table (covers old data
            # where the denormalised pointer wasn't set).
            row = self.db.execute(
                """SELECT o.id FROM rwa_flat_owners fo
                     JOIN rwa_owners o ON o.id = fo.owner_id
                    WHERE fo.flat_id=? AND fo.role='OWNER'
                          AND fo.is_primary=1 LIMIT 1""",
                (flat_id,),
            ).fetchone()
            target_id = row["id"] if row else None
        if not target_id:
            return None
        return self.db.execute(
            "SELECT * FROM rwa_owners WHERE id=?", (target_id,),
        ).fetchone() and dict(self.db.execute(
            "SELECT * FROM rwa_owners WHERE id=?", (target_id,),
        ).fetchone())

    # ── Write ────────────────────────────────────────────────────────

    def add_flat(
        self,
        flat_no: str,
        *,
        block:                str = "",
        tower:                str = "",
        floor:                str = "",
        flat_type:            str = "",
        area_sqft:            Optional[float] = None,
        built_up_area_sqft:   Optional[float] = None,
        parking_count:        int   = 0,
        storage_no:           str   = "",
        ownership_type:       str   = "OWNED",
        occupation_status:    str   = "OWNER_OCCUPIED",
        bill_payer:           str   = "OWNER",
        sale_deed_date:       Optional[str] = None,
        possession_date:      Optional[str] = None,
        move_in_date:         Optional[str] = None,
        notes:                str = "",
    ) -> int:
        flat_no = (flat_no or "").strip()
        if not flat_no:
            raise ValueError("Flat number is required.")
        if occupation_status not in VALID_OCCUPATION:
            raise ValueError(
                f"Invalid occupation_status {occupation_status!r}; "
                f"expected one of {VALID_OCCUPATION}."
            )
        if bill_payer not in VALID_BILL_PAYER:
            raise ValueError(
                f"Invalid bill_payer {bill_payer!r}; "
                f"expected one of {VALID_BILL_PAYER}."
            )

        dupe = self.db.execute(
            "SELECT id FROM rwa_flats WHERE company_id=? AND flat_no=?",
            (self.company_id, flat_no),
        ).fetchone()
        if dupe:
            raise ValueError(f"Flat '{flat_no}' already exists.")

        # Auto-create the Sundry Debtor ledger. Reuse if it already
        # exists with the same name (e.g. from book migration).
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
               (company_id, flat_no, block, tower, floor, flat_type,
                area_sqft, built_up_area_sqft, parking_count, storage_no,
                ownership_type, occupation_status, bill_payer,
                sale_deed_date, possession_date,
                ledger_id, move_in_date, notes)
               VALUES (?,?,?,?,?,?, ?,?,?,?, ?,?,?, ?,?, ?,?,?)""",
            (
                self.company_id, flat_no,
                block or None, tower or None, floor or None,
                flat_type or None,
                area_sqft, built_up_area_sqft,
                int(parking_count or 0),
                storage_no or None,
                ownership_type or "OWNED",
                occupation_status, bill_payer,
                sale_deed_date or None, possession_date or None,
                ledger_id,
                move_in_date or None, notes or None,
            ),
        )
        self.db.commit()
        return cur.lastrowid

    def update_flat(self, flat_id: int, **kwargs) -> None:
        existing = self.get_flat(flat_id)
        if not existing:
            raise ValueError("Flat not found.")

        # Rename guard: if flat_no changes and the ledger has any
        # voucher_lines, refuse — historical references must stay readable.
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

        # Validate enum values if present.
        if "occupation_status" in kwargs and kwargs["occupation_status"] \
                and kwargs["occupation_status"] not in VALID_OCCUPATION:
            raise ValueError(
                f"Invalid occupation_status {kwargs['occupation_status']!r}"
            )
        if "bill_payer" in kwargs and kwargs["bill_payer"] \
                and kwargs["bill_payer"] not in VALID_BILL_PAYER:
            raise ValueError(
                f"Invalid bill_payer {kwargs['bill_payer']!r}"
            )

        sets, params = [], []
        for k, v in kwargs.items():
            if k not in _FLAT_EDITABLE:
                continue
            if k == "active":
                v = int(bool(v))
            if k == "parking_count":
                v = int(v or 0)
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

    def set_primary_owner(self, flat_id: int, owner_id: int) -> None:
        """Set the flat's primary-owner denormalised pointer and mirror
        the change into rwa_flat_owners (clear other OWNER is_primary,
        ensure this owner has an OWNER row)."""
        self._set_primary_role(flat_id, owner_id, "OWNER",
                                "primary_owner_id")

    def set_primary_tenant(self, flat_id: int, owner_id: Optional[int]) -> None:
        """Set / clear the flat's primary tenant. Passing owner_id=None
        clears the pointer (e.g. when a tenant moves out)."""
        if owner_id is None:
            self.db.execute(
                "UPDATE rwa_flats SET primary_tenant_id=NULL "
                " WHERE id=? AND company_id=?",
                (flat_id, self.company_id),
            )
            self.db.commit()
            return
        self._set_primary_role(flat_id, owner_id, "TENANT",
                                "primary_tenant_id")

    def _set_primary_role(
        self, flat_id: int, owner_id: int, role: str, ptr_column: str,
    ) -> None:
        # 1) Make sure a link exists for (flat, owner, role); insert if
        #    missing.
        existing_link = self.db.execute(
            "SELECT id FROM rwa_flat_owners "
            " WHERE flat_id=? AND owner_id=? AND role=?",
            (flat_id, owner_id, role),
        ).fetchone()
        if existing_link is None:
            self.db.execute(
                "INSERT INTO rwa_flat_owners "
                " (flat_id, owner_id, role, is_primary) VALUES (?,?,?,1)",
                (flat_id, owner_id, role),
            )
        else:
            # Clear other primaries for this flat+role, mark this one.
            self.db.execute(
                "UPDATE rwa_flat_owners SET is_primary=0 "
                " WHERE flat_id=? AND role=?",
                (flat_id, role),
            )
            self.db.execute(
                "UPDATE rwa_flat_owners SET is_primary=1 WHERE id=?",
                (existing_link["id"],),
            )
        # 2) Update the denormalised pointer on rwa_flats.
        self.db.execute(
            f"UPDATE rwa_flats SET {ptr_column}=? "
            "WHERE id=? AND company_id=?",
            (owner_id, flat_id, self.company_id),
        )
        self.db.commit()

    def set_bill_payer(self, flat_id: int, who: str) -> None:
        if who not in VALID_BILL_PAYER:
            raise ValueError(f"bill_payer must be one of {VALID_BILL_PAYER}")
        self.update_flat(flat_id, bill_payer=who)

    def deactivate_flat(self, flat_id: int) -> None:
        self.update_flat(flat_id, active=0)

    def reactivate_flat(self, flat_id: int) -> None:
        self.update_flat(flat_id, active=1)

    # ── Owner ↔ Flat link management ─────────────────────────────────

    def owners_for_flat(self, flat_id: int) -> list[dict]:
        rows = self.db.execute(
            """SELECT fo.id AS link_id, fo.role, fo.is_primary, fo.since_date,
                      fo.tenancy_from, fo.tenancy_to,
                      fo.police_verification_ref, fo.police_verification_date,
                      fo.monthly_rent, fo.security_deposit, fo.lease_doc_path,
                      o.id AS owner_id, o.name, o.primary_phone, o.email,
                      o.preferred_payment_mode, o.upi_id, o.is_resident
                 FROM rwa_flat_owners fo
                 JOIN rwa_owners o ON o.id = fo.owner_id
                WHERE fo.flat_id = ?
             ORDER BY fo.is_primary DESC, fo.role, o.name""",
            (flat_id,),
        ).fetchall()
        return [dict(r) for r in rows]

    def assign_owner(
        self,
        flat_id: int, owner_id: int,
        *,
        role: str = "OWNER",
        is_primary: bool = False,
        since_date: Optional[str] = None,
        # Tenancy-only fields — ignored when role != TENANT
        tenancy_from:               Optional[str]   = None,
        tenancy_to:                 Optional[str]   = None,
        police_verification_ref:    Optional[str]   = None,
        police_verification_date:   Optional[str]   = None,
        monthly_rent:               Optional[float] = None,
        security_deposit:           Optional[float] = None,
        lease_doc_path:             Optional[str]   = None,
    ) -> int:
        role = (role or "OWNER").upper()
        if role not in VALID_LINK_ROLES:
            raise ValueError(f"Invalid role {role!r}; expected one of {VALID_LINK_ROLES}")

        if is_primary:
            # Clear other primaries on this flat *for the same role* —
            # OWNER and TENANT each have their own primary.
            self.db.execute(
                "UPDATE rwa_flat_owners SET is_primary=0 "
                " WHERE flat_id=? AND role=?",
                (flat_id, role),
            )
        try:
            cur = self.db.execute(
                """INSERT INTO rwa_flat_owners
                   (flat_id, owner_id, role, is_primary, since_date,
                    tenancy_from, tenancy_to,
                    police_verification_ref, police_verification_date,
                    monthly_rent, security_deposit, lease_doc_path)
                   VALUES (?,?,?,?,?, ?,?, ?,?, ?,?,?)""",
                (
                    flat_id, owner_id, role, int(bool(is_primary)),
                    since_date or None,
                    (tenancy_from or None)             if role == "TENANT" else None,
                    (tenancy_to or None)               if role == "TENANT" else None,
                    (police_verification_ref or None)  if role == "TENANT" else None,
                    (police_verification_date or None) if role == "TENANT" else None,
                    (monthly_rent)                     if role == "TENANT" else None,
                    (security_deposit)                 if role == "TENANT" else None,
                    (lease_doc_path or None)           if role == "TENANT" else None,
                ),
            )
        except Exception as e:
            raise ValueError(
                "This person is already assigned to this flat in that role."
            ) from e

        # If marking primary, mirror into rwa_flats denormalised pointer.
        if is_primary:
            ptr_col = "primary_tenant_id" if role == "TENANT" else "primary_owner_id"
            self.db.execute(
                f"UPDATE rwa_flats SET {ptr_col}=? "
                "WHERE id=? AND company_id=?",
                (owner_id, flat_id, self.company_id),
            )
            # If we just attached a tenant, occupation flips to RENTED.
            if role == "TENANT":
                self.db.execute(
                    "UPDATE rwa_flats SET occupation_status='RENTED' "
                    "WHERE id=? AND company_id=?",
                    (flat_id, self.company_id),
                )
        self.db.commit()
        return cur.lastrowid

    def update_link(self, link_id: int, **kwargs) -> None:
        """Edit a rwa_flat_owners row — useful for renewing a tenancy
        (updating tenancy_to + police_verification_date) without
        creating a new link."""
        sets, params = [], []
        for k, v in kwargs.items():
            if k not in _LINK_EDITABLE:
                continue
            if k == "is_primary":
                v = int(bool(v))
            sets.append(f"{k}=?")
            params.append(v)
        if not sets:
            return
        params.append(link_id)
        self.db.execute(
            f"UPDATE rwa_flat_owners SET {', '.join(sets)} WHERE id=?",
            params,
        )
        self.db.commit()

    def unassign_owner(self, link_id: int) -> None:
        # Look up before delete so we can clear the denormalised pointer
        # on rwa_flats if this was the primary OWNER/TENANT row.
        row = self.db.execute(
            "SELECT flat_id, owner_id, role, is_primary FROM rwa_flat_owners WHERE id=?",
            (link_id,),
        ).fetchone()
        self.db.execute(
            "DELETE FROM rwa_flat_owners WHERE id=?", (link_id,),
        )
        if row and row["is_primary"]:
            ptr_col = (
                "primary_tenant_id" if row["role"] == "TENANT"
                else "primary_owner_id"
            )
            self.db.execute(
                f"UPDATE rwa_flats SET {ptr_col}=NULL WHERE id=?",
                (row["flat_id"],),
            )
            # If we removed the primary tenant, occupation reverts to
            # owner-occupied (or vacant — caller can correct via UI).
            if row["role"] == "TENANT":
                self.db.execute(
                    "UPDATE rwa_flats SET occupation_status='OWNER_OCCUPIED' "
                    "WHERE id=?",
                    (row["flat_id"],),
                )
        self.db.commit()


# ─────────────────────────────────────────────────────────────────────
# OwnersService
# ─────────────────────────────────────────────────────────────────────

class OwnersService:
    """CRUD for rwa_owners (members + tenants live in this table)."""

    def __init__(self, db, company_id: int):
        self.db = db
        self.company_id = company_id

    def list_owners(self, active_only: bool = True) -> list[dict]:
        q = """SELECT o.id, o.name, o.primary_phone, o.email,
                      o.pan, o.aadhaar_last4,
                      o.kyc_id_type, o.kyc_id_number,
                      o.alternate_phone,
                      o.correspondence_address, o.is_resident,
                      o.emergency_name, o.emergency_phone,
                      o.preferred_payment_mode, o.upi_id,
                      o.bank_account_no, o.bank_ifsc,
                      o.bank_account_holder_name, o.nach_mandate_ref,
                      o.notes, o.photo_path, o.active,
                      (SELECT COUNT(*) FROM rwa_flat_owners fo
                          JOIN rwa_flats f ON f.id = fo.flat_id
                         WHERE fo.owner_id = o.id AND f.active = 1)
                        AS flat_count,
                      (SELECT GROUP_CONCAT(f.flat_no || ' (' || fo.role || ')', ', ')
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

        mode = (kwargs.get("preferred_payment_mode") or "").strip().upper() or None
        if mode and mode not in VALID_PAYMENT_MODES:
            raise ValueError(
                f"preferred_payment_mode must be one of {VALID_PAYMENT_MODES}"
            )

        cur = self.db.execute(
            """INSERT INTO rwa_owners
               (company_id, name, primary_phone, alternate_phone, email,
                pan, aadhaar_last4,
                kyc_id_type, kyc_id_number, photo_path,
                correspondence_address, is_resident,
                emergency_name, emergency_phone,
                preferred_payment_mode, upi_id,
                bank_account_no, bank_ifsc, bank_account_holder_name,
                nach_mandate_ref, notes)
               VALUES (?,?,?,?,?, ?,?, ?,?,?, ?,?, ?,?, ?,?, ?,?,?, ?,?)""",
            (
                self.company_id, name,
                (kwargs.get("primary_phone")   or None),
                (kwargs.get("alternate_phone") or None),
                (kwargs.get("email")           or None),
                (kwargs.get("pan")             or None),
                (kwargs.get("aadhaar_last4")   or None),
                (kwargs.get("kyc_id_type")     or None),
                (kwargs.get("kyc_id_number")   or None),
                (kwargs.get("photo_path")      or None),
                (kwargs.get("correspondence_address") or None),
                int(bool(kwargs.get("is_resident", 1))),
                (kwargs.get("emergency_name")  or None),
                (kwargs.get("emergency_phone") or None),
                mode,
                (kwargs.get("upi_id")          or None),
                (kwargs.get("bank_account_no") or None),
                (kwargs.get("bank_ifsc")       or None),
                (kwargs.get("bank_account_holder_name") or None),
                (kwargs.get("nach_mandate_ref") or None),
                (kwargs.get("notes")           or None),
            ),
        )
        self.db.commit()
        return cur.lastrowid

    def update_owner(self, owner_id: int, **kwargs) -> None:
        if "preferred_payment_mode" in kwargs:
            mode = (kwargs["preferred_payment_mode"] or "").strip().upper() or None
            if mode and mode not in VALID_PAYMENT_MODES:
                raise ValueError(
                    f"preferred_payment_mode must be one of {VALID_PAYMENT_MODES}"
                )
            kwargs["preferred_payment_mode"] = mode

        sets, params = [], []
        for k, v in kwargs.items():
            if k not in _OWNER_EDITABLE:
                continue
            if k in ("active", "is_resident"):
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
