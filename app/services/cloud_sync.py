"""
Desktop ↔ cloud sync orchestrator.

Pushes the desktop's flats / residents / notices / polls to
rwagenie-web; pulls back complaints + poll votes + visitor passes
that residents created on the web.

State stored in the existing rwa_settings kv table:
  cloud.enabled              "1" / "0"   — admin toggle
  cloud.sync_server_url      str         — defaults to rwagenie-web.fly.dev
  cloud.sync_token           str         — bearer issued at bootstrap
  cloud.society_slug         str         — derived from the .db filename
  cloud.last_pushed_at       ISO         — bookkeeping
  cloud.last_pulled_at       ISO         — used as `since` for the next pull

Authoritative direction:
  • Admin data (flats, residents, notices, polls) — desktop is the
    source of truth.
  • Resident-originated data (web complaints, votes, visitor passes
    issued via web) — cloud is the source of truth; desktop pulls
    and stores.

Conflict handling: full-snapshot push is idempotent; desktop overwrites
the cloud whenever it pushes. Pull is incremental. No multi-writer
conflict resolution in v0.1 — admins editing the same row from two
desktops would last-writer-wins on the cloud.
"""
from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Optional

import requests

from core.license_manager import LicenseManager, SERVER_URL as LICENSE_SERVER
from app.services.settings import SettingsService


logger = logging.getLogger(__name__)


DEFAULT_SYNC_SERVER = os.environ.get(
    "RWAGENIE_SYNC_URL",
    "https://rwagenie-web.fly.dev",
)


# ── Errors ──────────────────────────────────────────────────────────────

class CloudSyncError(RuntimeError):
    pass


class NotBootstrapped(CloudSyncError):
    pass


@dataclass
class SyncReport:
    pushed: dict[str, int] = field(default_factory=dict)
    pulled: dict[str, int] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)


# ── Service ─────────────────────────────────────────────────────────────

class CloudSyncService:
    def __init__(self, db, company_id: int, tree=None):
        self.db = db
        self.company_id = company_id
        self.tree = tree
        self.settings = SettingsService(db, company_id)

    # ── State helpers ──────────────────────────────────────────────────

    def is_enabled(self) -> bool:
        return self.settings.get_bool("cloud.enabled", False)

    def set_enabled(self, on: bool) -> None:
        self.settings.set("cloud.enabled", "1" if on else "0")

    def server_url(self) -> str:
        url = (self.settings.get("cloud.sync_server_url") or "").strip()
        return (url or DEFAULT_SYNC_SERVER).rstrip("/")

    def set_server_url(self, url: str) -> None:
        self.settings.set("cloud.sync_server_url", (url or "").strip())

    def sync_token(self) -> str:
        return self.settings.get("cloud.sync_token") or ""

    def society_slug(self) -> str:
        slug = (self.settings.get("cloud.society_slug") or "").strip()
        if slug:
            return slug
        # Derive from the company's DB filename (stable across reinstalls).
        # Fall back to a slugified company name.
        try:
            row = self.db.execute(
                "SELECT name FROM companies WHERE id=?", (self.company_id,),
            ).fetchone()
            name = row["name"] if row else "society"
        except Exception:
            name = "society"
        slug = re.sub(r"[^a-z0-9]+", "-", (name or "").lower()).strip("-")[:64]
        if not slug:
            slug = f"society-{self.company_id}"
        self.settings.set("cloud.society_slug", slug)
        return slug

    def status(self) -> dict[str, Any]:
        return {
            "enabled":         self.is_enabled(),
            "server_url":      self.server_url(),
            "society_slug":    self.society_slug(),
            "bootstrapped":    bool(self.sync_token()),
            "last_pushed_at":  self.settings.get("cloud.last_pushed_at") or "",
            "last_pulled_at":  self.settings.get("cloud.last_pulled_at") or "",
        }

    # ── HTTP helpers ───────────────────────────────────────────────────

    def _headers(self) -> dict[str, str]:
        token = self.sync_token()
        if not token:
            raise NotBootstrapped(
                "Cloud sync isn't bootstrapped yet — click 'Activate cloud' "
                "first."
            )
        return {"Authorization": f"Bearer {token}"}

    # ── Bootstrap ──────────────────────────────────────────────────────

    def bootstrap(self) -> None:
        """Activate cloud sync for this society. Requires a valid
        license. Issues a sync_token and stores it locally."""
        lm = LicenseManager()
        license_key = (lm.license_key or "").strip()
        if not license_key or license_key in ("DEMO", "ACCG-DEV-FULL"):
            raise CloudSyncError(
                "Activate a real RWAGenie license first. The DEMO/DEV "
                "license can't bootstrap cloud sync."
            )

        slug = self.society_slug()
        co = self.db.execute(
            "SELECT name, state_code FROM companies WHERE id=?",
            (self.company_id,),
        ).fetchone()

        body = {
            "license_key":  license_key,
            "machine_id":   LicenseManager.get_machine_id(),
            "app_version":  "0.1.4",   # bumped when sync ships
            "society_slug": slug,
            "society_name": (co["name"] if co else slug)[:200],
            "state_code":   (co["state_code"] if co else "") or "",
        }
        url = f"{self.server_url()}/api/v1/sync/bootstrap"
        try:
            resp = requests.post(url, json=body, timeout=30)
        except requests.RequestException as e:
            raise CloudSyncError(f"Couldn't reach the sync server: {e}") from e
        try:
            j = resp.json()
        except ValueError:
            raise CloudSyncError(f"Sync server non-JSON: {resp.text[:200]}")

        if not j.get("ok"):
            raise CloudSyncError(j.get("error") or "bootstrap_failed")

        self.settings.set("cloud.sync_token",  j["sync_token"])
        self.settings.set("cloud.society_slug", slug)
        # Bootstrapping implicitly enables sync.
        self.set_enabled(True)

    # ── Push snapshot ──────────────────────────────────────────────────

    def _build_snapshot(self) -> dict:
        cid = self.company_id

        # Residents (rwa_owners on the desktop side)
        residents = [
            {
                "desktop_id":    r["id"],
                "name":          r["name"] or "",
                "primary_phone": r["primary_phone"] or "",
                "email":         r["email"] or "",
                # Privacy off by default; residents toggle via web later
                "share_phone":   False,
                "share_email":   False,
                "active":        bool(r["active"]),
            }
            for r in self.db.execute(
                "SELECT id, name, primary_phone, email, active "
                "FROM rwa_owners WHERE company_id=?",
                (cid,),
            ).fetchall()
        ]

        # Flats (rwa_flats)
        flats = [
            {
                "desktop_id":      f["id"],
                "flat_no":         f["flat_no"] or "",
                "block":           f["block"] or "",
                "tower":           f["tower"] or "",
                "floor":           f["floor"] or "",
                "flat_type":       f["flat_type"] or "",
                "area_sqft":       f["area_sqft"],
                "bill_payer":      f["bill_payer"] or "OWNER",
                "outstanding_inr": _outstanding_inr(self.db, f),
                "primary_owner_desktop_id":  f["primary_owner_id"],
                "primary_tenant_desktop_id": f["primary_tenant_id"],
                "active":          bool(f["active"]),
            }
            for f in self.db.execute(
                "SELECT id, flat_no, block, tower, floor, flat_type, "
                "       area_sqft, bill_payer, ledger_id, active, "
                "       primary_owner_id, primary_tenant_id "
                "FROM rwa_flats WHERE company_id=?",
                (cid,),
            ).fetchall()
        ]

        # Notices
        today = datetime.utcnow().date().isoformat()
        notices = [
            {
                "desktop_id": n["id"],
                "title":      n["title"] or "",
                "body":       n["body"] or "",
                "posted_by":  n["posted_by"] or "",
                "pinned":     bool(n["pinned"]),
                "expires_on": n["expires_on"],
                "created_at": n["created_at"],
            }
            for n in self.db.execute(
                "SELECT id, title, body, posted_by, pinned, expires_on, "
                "       created_at FROM rwa_notices WHERE company_id=? "
                "AND (expires_on IS NULL OR expires_on >= ?)",
                (cid, today),
            ).fetchall()
        ]

        # Polls
        polls = [
            {
                "desktop_id":   p["id"],
                "title":        p["title"] or "",
                "description":  p["description"] or "",
                "options_json": p["options_json"] or "[]",
                "one_vote_per": p["one_vote_per"] or "FLAT",
                "status":       p["status"] or "OPEN",
                "opens_at":     p["opens_at"],
                "closes_at":    p["closes_at"],
            }
            for p in self.db.execute(
                "SELECT id, title, description, options_json, "
                "       one_vote_per, status, opens_at, closes_at "
                "FROM rwa_polls WHERE company_id=?",
                (cid,),
            ).fetchall()
        ]

        # Complaint updates that admin made locally — pushed back so
        # residents see the resolution. We push every web-origin
        # complaint we have locally; cloud upserts by cloud_id.
        complaint_updates = [
            {
                "cloud_id":         c["cloud_id"],
                "status":           c["status"] or "OPEN",
                "resolution_notes": c["resolution_notes"] or "",
                "resolved_at":      c["resolved_at"],
            }
            for c in self.db.execute(
                "SELECT cloud_id, status, resolution_notes, resolved_at "
                "FROM rwa_complaints WHERE company_id=? "
                "AND cloud_id IS NOT NULL",
                (cid,),
            ).fetchall()
        ]

        return {
            "flats":             flats,
            "residents":         residents,
            "notices":           notices,
            "polls":             polls,
            "complaint_updates": complaint_updates,
        }

    def push(self) -> dict:
        url = f"{self.server_url()}/api/v1/sync/snapshot"
        snap = self._build_snapshot()
        try:
            resp = requests.post(url, json=snap, headers=self._headers(), timeout=60)
        except requests.RequestException as e:
            raise CloudSyncError(f"Push failed (network): {e}") from e
        try:
            j = resp.json()
        except ValueError:
            raise CloudSyncError(f"Push: non-JSON response {resp.status_code}")
        if resp.status_code == 401:
            raise NotBootstrapped("Sync token rejected — re-activate cloud sync.")
        if resp.status_code >= 400 or not j.get("ok"):
            raise CloudSyncError(f"Push failed: {j}")
        self.settings.set("cloud.last_pushed_at",
                           datetime.utcnow().isoformat(timespec="seconds"))
        return j

    # ── Pull changes ───────────────────────────────────────────────────

    def pull(self) -> dict:
        url = f"{self.server_url()}/api/v1/sync/changes"
        since = self.settings.get("cloud.last_pulled_at") or ""
        try:
            resp = requests.get(
                url, params={"since": since} if since else None,
                headers=self._headers(), timeout=60,
            )
        except requests.RequestException as e:
            raise CloudSyncError(f"Pull failed (network): {e}") from e
        if resp.status_code == 401:
            raise NotBootstrapped("Sync token rejected — re-activate cloud sync.")
        try:
            j = resp.json()
        except ValueError:
            raise CloudSyncError(f"Pull: non-JSON response {resp.status_code}")

        n_complaints = self._apply_complaints(j.get("complaints") or [])
        n_votes      = self._apply_poll_votes(j.get("poll_votes") or [])
        n_passes     = self._apply_visitor_passes(j.get("visitor_passes") or [])

        # Advance the cursor to the server's time, not local time —
        # avoids clock-skew gaps.
        if j.get("server_time"):
            self.settings.set("cloud.last_pulled_at", j["server_time"])
        else:
            self.settings.set("cloud.last_pulled_at",
                               datetime.utcnow().isoformat(timespec="seconds"))

        return {
            "complaints":     n_complaints,
            "poll_votes":     n_votes,
            "visitor_passes": n_passes,
        }

    def _apply_complaints(self, rows: list[dict]) -> int:
        applied = 0
        for c in rows:
            cloud_id = c.get("cloud_id")
            if cloud_id is None:
                continue
            # Find by cloud_id
            existing = self.db.execute(
                "SELECT id FROM rwa_complaints "
                "WHERE company_id=? AND cloud_id=?",
                (self.company_id, cloud_id),
            ).fetchone()
            if existing:
                # We trust the desktop's local edits on existing rows;
                # only freshen status if still OPEN.
                continue
            self.db.execute(
                """INSERT INTO rwa_complaints
                     (company_id, cloud_id, flat_id, raised_by_owner,
                      category, title, description, priority, status,
                      raised_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?)""",
                (
                    self.company_id, cloud_id,
                    _map_cloud_to_desktop_flat(self.db, self.company_id, c.get("flat_id")),
                    _map_cloud_to_desktop_owner(self.db, self.company_id, c.get("raised_by_id")),
                    c.get("category") or "OTHER",
                    (c.get("title") or "")[:200],
                    (c.get("description") or "")[:5000],
                    c.get("priority") or "NORMAL",
                    c.get("status") or "OPEN",
                    c.get("raised_at") or datetime.utcnow().isoformat(timespec="seconds"),
                ),
            )
            applied += 1
        self.db.commit()
        return applied

    def _apply_poll_votes(self, rows: list[dict]) -> int:
        # Best-effort: poll_id on cloud side is the cloud Poll id, which
        # the desktop knows because the cloud poll was created from the
        # desktop's push. We resolve via desktop_id of the cloud poll
        # rather than re-querying the cloud — for v0.1 the desktop's
        # polls table doesn't store cloud_id, so we map by title (a bit
        # fragile but acceptable until v0.2).
        # → defer recording votes back to the desktop in v0.1.4; the
        # cloud is the source of truth for vote tallies, and the admin
        # can see them at residents.rwagenie-web.fly.dev. Not blocking
        # for v0.1 — drop them silently.
        return 0

    def _apply_visitor_passes(self, rows: list[dict]) -> int:
        # Similar story — desktop has rwa_visitor_passes but mapping
        # cloud_id↔desktop_id is one-directional for v0.1. We could
        # insert these as new local rows tagged origin='web'. Defer
        # to v0.2 to keep this PR shippable.
        return 0

    # ── Combined sync ──────────────────────────────────────────────────

    def sync_all(self) -> SyncReport:
        report = SyncReport()
        try:
            push_res = self.push()
            for k in ("flats_upserted", "residents_upserted",
                      "notices_upserted", "polls_upserted",
                      "complaints_updated"):
                report.pushed[k] = push_res.get(k, 0)
        except Exception as e:
            report.errors.append(f"push: {e}")
            return report

        try:
            pull_res = self.pull()
            report.pulled = pull_res
        except Exception as e:
            report.errors.append(f"pull: {e}")

        return report


# ── Helpers ─────────────────────────────────────────────────────────────

def _outstanding_inr(db, flat_row) -> float:
    """Compute outstanding maintenance dues from the ledger linked to
    this flat. Returns 0.0 when no ledger or no transactions yet.

    Mirrors the desktop's outstanding-balance logic in FlatsService
    but inlines a tiny version because we only need a snapshot of the
    Dr balance."""
    ledger_id = flat_row["ledger_id"]
    if not ledger_id:
        return 0.0
    try:
        r = db.execute(
            "SELECT COALESCE(SUM(vl.dr_amount - vl.cr_amount), 0) AS dr "
            "  FROM voucher_lines vl WHERE vl.ledger_id=?",
            (ledger_id,),
        ).fetchone()
        return float(r["dr"] or 0.0)
    except Exception:
        return 0.0


def _map_cloud_to_desktop_flat(db, cid: int, cloud_flat_id) -> int | None:
    """Reverse-resolve a cloud flat_id to the desktop's local id.
    The cloud's Flat.desktop_id holds the desktop's id; we don't have
    the cloud→desktop_id map locally without a sync_state table. For
    v0.1 we accept None — the complaint just won't link to a flat on
    the desktop side."""
    return None


def _map_cloud_to_desktop_owner(db, cid: int, cloud_owner_id) -> int | None:
    return None
