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

from app.pages.flats_page            import FlatsPage
from app.pages.members_page          import MembersPage
from app.pages.notices_page          import NoticeBoardPage
from app.pages.complaints_page       import ComplaintsPage
from app.pages.broadcasts_page       import BroadcastsPage
from app.pages.polls_page            import PollsPage
from app.pages.visitor_passes_page   import VisitorPassPage
from app.pages.wallet_page           import WalletPage
from app.pages.cloud_sync_page       import CloudSyncPage
from app.pages.users_page            import UsersPage
from app.pages.audit_log_page        import AuditLogPage
from app.models                       import apply_rwa_schema
from app.services.auth                import AuthSession
from app.sidebar                      import (
    CollapsibleSection, SECTION_ORDER, section_for_label,
)


class RWAMainWindow(_AGMainWindow):
    """RWAGenie main window. Inherits all accounting pages from AG;
    adds Flats + Members (and future RWA pages) on top.

    Feature gating uses the same `lmgr.has_feature("rwa_*")` mechanism
    as AG — the license server returns RWA features when product=rwagenie.
    Pages only mount when the relevant feature is unlocked for the user's
    plan.
    """

    def __init__(self, db, company_id: int, tree, engine,
                 auth: AuthSession | None = None):
        # Stash the authenticated user *before* super().__init__ runs so
        # AG's _build_pages() callbacks (if any of them ever consult it)
        # can see it. Pages reach this via `self.parent().auth` or via
        # an explicit `auth=` constructor arg.
        self.auth = auth

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

        # RWAGenie window title overrides AG's "AccGenie — <co>" and
        # includes the signed-in user/role so the admin can see at a
        # glance whose session they're in.
        try:
            co_row = db.execute(
                "SELECT name FROM companies WHERE id=?", (company_id,),
            ).fetchone()
            co_name = co_row["name"] if co_row else ""
        except Exception:
            co_name = ""
        bits = ["RWAGenie"]
        if co_name:
            bits.append(co_name)
        if self.auth is not None:
            bits.append(self.auth.label())
        self.setWindowTitle("  —  ".join(bits))

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

        # Sidebar label adapts to the society's unit type (FLAT/PLOT).
        # Read at startup; changing it via the Flats page's "⚙ Society"
        # dialog requires an app restart for the sidebar to relabel.
        try:
            from app.services.settings import SettingsService as _S
            _flats_label = _S(self.db, self.company_id).unit_noun(plural=True)
        except Exception:
            _flats_label = "Flats"
        _add(_flats_label, "🏠", FlatsPage,   "rwa_flat_ledger")
        _add("Members",    "👥", MembersPage, "rwa_member_directory")

        # ── Free-tier pages — full CRUD shipping with v0.1. Schemas
        # (rwa_notices / _complaints / _broadcasts / _polls /
        # _visitor_passes) and their services back each page.
        def _add_rwa(label, icon, page_cls, feature):
            if lmgr is None or lmgr.has_feature(feature):
                page = page_cls(self.db, self.company_id, self.tree)
                self.register_page(label, icon, page)
            else:
                page = self._locked_page(feature, "STANDARD", label)
                self.register_page(label, icon, page)

        _add_rwa("Notice Board", "📢", NoticeBoardPage, "rwa_notice_board")
        _add_rwa("Complaints",   "⚠",  ComplaintsPage,   "rwa_complaint_tracking")
        _add_rwa("Broadcasts",   "📣", BroadcastsPage,   "rwa_broadcast_messaging")
        _add_rwa("Polls",        "🗳", PollsPage,        "rwa_polls")
        _add_rwa("Visitor Pass", "🎫", VisitorPassPage,  "rwa_visitor_pass")

        # Wallet — SMS balance. Available on every tier (cloud features
        # are free; wallet meters the SMS pass-through). No feature gate.
        self.register_page(
            "Wallet", "💰",
            WalletPage(self.db, self.company_id, self.tree),
        )

        # Cloud Sync — bootstrap + manual sync to rwagenie-web. Also
        # always-on (the wallet is the monetisation surface; cloud
        # itself is free).
        self.register_page(
            "Cloud Sync", "☁",
            CloudSyncPage(self.db, self.company_id, self.tree),
        )

        # ── Admin pages — role-gated. Skipped entirely (not even shown
        # as locked placeholders) for users whose role doesn't grant
        # the permission, because a non-admin shouldn't even be teased
        # by their existence in the sidebar.
        if self.auth is not None:
            if self.auth.can("manage_users"):
                self.register_page(
                    "Users", "👤",
                    UsersPage(self.db, self.company_id, self.tree, self.auth),
                )
            if self.auth.can("view_audit"):
                self.register_page(
                    "Audit Log", "📜",
                    AuditLogPage(self.db, self.company_id, self.tree, self.auth),
                )

        # Reorganise the linear sidebar into collapsible sections —
        # see app/sidebar.py for the grouping rules. Must run after
        # every register_page() call so we see all the buttons.
        self._regroup_sidebar_into_sections()

    # ── Sidebar post-processing ─────────────────────────────────────────────

    def _regroup_sidebar_into_sections(self) -> None:
        """
        Take the flat list AG built (self._nav_container of NavButtons +
        QLabel section headers) and rebuild it as collapsible sections.

        AG's register_page() appended widgets linearly. RWAGenie's
        sidebar would run 30+ rows tall without grouping; collapsing
        Accounting / Reports / Tax / Data / Settings by default keeps
        RWA pages on the visible window.
        """
        # 1. Bucket each page's NavButton by which section it belongs in.
        buckets: dict[str, list] = {name: [] for name, _ in SECTION_ORDER}
        for label, _icon, _widget, btn in self._pages:
            sec_name = section_for_label(label)
            if sec_name not in buckets:
                sec_name = "Other"
            buckets[sec_name].append(btn)

        # 2. Detach everything currently in the nav container — this
        # includes the QLabel section headers AG added via the
        # `section_above` parameter on register_page(). We're replacing
        # those with the collapsible-section headers, so the originals
        # go away.
        while self._nav_container.count() > 0:
            item = self._nav_container.takeAt(0)
            w = item.widget()
            if w is not None:
                w.setParent(None)
                # Original section-header QLabels become orphans and
                # get GC'd. NavButtons we'll re-parent into sections
                # immediately, so they have a live owner before any GC
                # pass.

        # 3. Rebuild: one CollapsibleSection per non-empty bucket.
        for sec_name, expanded in SECTION_ORDER:
            btns = buckets.get(sec_name, [])
            if not btns:
                continue
            section = CollapsibleSection(sec_name, expanded=expanded)
            for btn in btns:
                section.add_button(btn)
            self._nav_container.addWidget(section)
