"""
RWAGenie main window — extends AccGenie's MainWindow.

We inherit every accounting page AG provides (Day Book, Reports, GST,
Bank Reco, etc.) for free, then bolt RWA-specific pages on top.

The base AG `MainWindow.__init__` runs `_build_pages()` which mounts
the accounting sidebar. We override `__init__` (or rather: call into
super and then add) so we register the RWA pages *after* AG's are in
place — they land at the bottom of the sidebar grouped under "RWA".
"""
from __future__ import annotations

from ui.main_window import MainWindow as _AGMainWindow

from app.pages.flats_page    import FlatsPage
from app.pages.members_page  import MembersPage
from app.pages._coming_soon  import ComingSoonPage
from app.models              import apply_rwa_schema


class RWAMainWindow(_AGMainWindow):
    """RWAGenie main window. Inherits all accounting pages from AG;
    adds Flats + Members (and future RWA pages) on top.

    Feature gating uses the same `lmgr.has_feature("rwa_*")` mechanism
    as AG — the license server returns RWA features when product=rwagenie.
    Pages only mount when the relevant feature is unlocked for the user's
    plan.
    """

    def __init__(self, db, company_id: int, tree, engine):
        # Make sure the RWA tables exist before we instantiate pages that
        # query them. Idempotent — CREATE TABLE IF NOT EXISTS.
        try:
            apply_rwa_schema(db)
        except Exception:
            # Don't crash the app if schema migration hits an edge case;
            # surface in logs but let the user open the company.
            import logging, traceback
            logging.getLogger(__name__).error(
                "apply_rwa_schema failed:\n%s", traceback.format_exc()
            )

        # AG's MainWindow runs _build_pages() inside __init__, so by the
        # time super().__init__ returns the sidebar already has all
        # accounting pages.
        super().__init__(db, company_id, tree, engine)

        # RWAGenie window title overrides AG's "AccGenie — <co>".
        try:
            co_row = db.execute(
                "SELECT name FROM companies WHERE id=?", (company_id,),
            ).fetchone()
            co_name = co_row["name"] if co_row else ""
        except Exception:
            co_name = ""
        self.setWindowTitle(
            f"RWAGenie — {co_name}" if co_name else "RWAGenie"
        )

        self._register_rwa_pages()

    def _register_rwa_pages(self) -> None:
        lmgr = getattr(self, "license_mgr", None)

        # Section header before the first RWA page.
        first_added = False

        def _add(label, icon, page_cls, feature: str):
            nonlocal first_added
            section = "RWA" if not first_added else ""
            first_added = True
            if lmgr is None or lmgr.has_feature(feature):
                page = page_cls(self.db, self.company_id, self.tree)
                self.register_page(label, icon, page, section_above=section)
            else:
                # Show a locked placeholder so the user knows the feature
                # exists. Reuses AG's _locked_page helper.
                placeholder = self._locked_page(feature, "STANDARD", label)
                self.register_page(label, icon, placeholder, section_above=section)

        _add("Flats",   "🏠", FlatsPage,   "rwa_flat_ledger")
        _add("Members", "👥", MembersPage, "rwa_member_directory")

        # ── Free-tier scaffolding — sidebar entries shipped with v0.1 so
        # the user sees the full intended surface. Schemas (rwa_notices /
        # _complaints / _broadcasts / _polls / _visitor_passes) already
        # exist in the company DB; only the CRUD UI is pending.
        def _stub(label, icon, feature, blurb):
            if lmgr is None or lmgr.has_feature(feature):
                page = ComingSoonPage(label, blurb)
            else:
                page = self._locked_page(feature, "STANDARD", label)
            self.register_page(label, icon, page)

        _stub("Notice Board", "📢", "rwa_notice_board",
              "Society-wide announcements visible to every member.")
        _stub("Complaints",   "⚠",  "rwa_complaint_tracking",
              "Track plumbing / electrical / security tickets to resolution.")
        _stub("Broadcasts",   "📣", "rwa_broadcast_messaging",
              "Targeted messages — emails today, SMS/WhatsApp once "
              "delivery providers are wired in.")
        _stub("Polls",        "🗳", "rwa_polls",
              "AGM resolutions, amenity votes. One-vote-per-flat or "
              "per-owner, configurable.")
        _stub("Visitor Pass", "🎫", "rwa_visitor_pass",
              "Gate-issued or pre-authorised entry passes with vehicle "
              "no + expected-arrival window.")
