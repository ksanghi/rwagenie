"""
Dev-time feature-gate bridge: AG license → RWAGenie features.

Why this exists
================
The AccGenie license your machine has (e.g. an AG PRO key) was minted
with `product='accgenie'`, so the license server returns AG-only
features on validate. The features list cached locally in
license.json doesn't contain `rwa_*` entries.

Result: clicking Flats / Members in RWAGenie hits the lock-out
"Upgrade to STANDARD" screen even though you have an AG PRO key.

The right end-state is to mint a real RWAGenie license
(`product='rwagenie'`) via the license server's admin CLI; on validate
the server merges AG features + RWA features for your tier and the
desktop caches the union.

Until that flow is wired end-to-end, this module monkey-patches the
AG `LicenseManager.has_feature` IN THE RWAGENIE PROCESS so that any
`rwa_*` feature ID resolves via the inline tier map below — same
mapping the license server's `features_for('rwagenie', plan)` would
have returned.

Safe properties:
  • Only patched inside `python rwagenie/main.py` runs. AccGenie's
    own desktop process is unaffected.
  • Original `has_feature` is delegated to first — non-RWA features
    keep their normal gating. We only add a *fallback* for `rwa_*`
    feature IDs.
  • Removing this file (and the `install()` call from app.main) reverts
    to pure license-server-driven gating with zero residue.

Remove this when:
  - The license server can mint product='rwagenie' keys end-to-end, AND
  - The desktop's first-run UX guides the user to enter an RWAGenie
    key (or a clean DEMO/Free path exists for new RWAGenie installs).
"""
from __future__ import annotations


# Mirrors license_server.plans.PLAN_FEATURES_RWA. Update both together
# until pricing_rwa.xlsx + bake_config replace this.
_RWA_FEATURES_BY_PLAN: dict[str, list[str]] = {
    "DEMO": [
        # DEMO mirrors PREMIUM in AG; carry the same convention forward.
        "rwa_flat_ledger", "rwa_receipt_tracking", "rwa_member_directory",
        "rwa_notice_board", "rwa_complaint_tracking", "rwa_broadcast_messaging",
        "rwa_polls", "rwa_visitor_pass", "rwa_basic_reports",
        "rwa_auto_billing", "rwa_late_fees", "rwa_facilities_booking",
        "rwa_asset_register", "rwa_advanced_reports",
        "rwa_whatsapp_invoices", "rwa_document_storage", "rwa_vendor_management",
    ],
    "FREE": [
        "rwa_flat_ledger", "rwa_receipt_tracking", "rwa_member_directory",
        "rwa_notice_board", "rwa_complaint_tracking", "rwa_broadcast_messaging",
        "rwa_polls", "rwa_visitor_pass", "rwa_basic_reports",
    ],
    "STANDARD": [
        "rwa_flat_ledger", "rwa_receipt_tracking", "rwa_member_directory",
        "rwa_notice_board", "rwa_complaint_tracking", "rwa_broadcast_messaging",
        "rwa_polls", "rwa_visitor_pass", "rwa_basic_reports",
        "rwa_auto_billing", "rwa_late_fees", "rwa_facilities_booking",
        "rwa_asset_register", "rwa_advanced_reports",
    ],
    "PRO": [
        "rwa_flat_ledger", "rwa_receipt_tracking", "rwa_member_directory",
        "rwa_notice_board", "rwa_complaint_tracking", "rwa_broadcast_messaging",
        "rwa_polls", "rwa_visitor_pass", "rwa_basic_reports",
        "rwa_auto_billing", "rwa_late_fees", "rwa_facilities_booking",
        "rwa_asset_register", "rwa_advanced_reports",
        "rwa_whatsapp_invoices", "rwa_document_storage", "rwa_vendor_management",
    ],
    "PREMIUM": [
        "rwa_flat_ledger", "rwa_receipt_tracking", "rwa_member_directory",
        "rwa_notice_board", "rwa_complaint_tracking", "rwa_broadcast_messaging",
        "rwa_polls", "rwa_visitor_pass", "rwa_basic_reports",
        "rwa_auto_billing", "rwa_late_fees", "rwa_facilities_booking",
        "rwa_asset_register", "rwa_advanced_reports",
        "rwa_whatsapp_invoices", "rwa_document_storage", "rwa_vendor_management",
    ],
}


_INSTALLED = False


def install() -> None:
    """Monkey-patch `core.license_manager.LicenseManager.has_feature` so
    `rwa_*` feature IDs resolve based on the user's current AG plan.

    Idempotent — safe to call more than once."""
    global _INSTALLED
    if _INSTALLED:
        return

    import core.license_manager as _lm

    _orig_has_feature = _lm.LicenseManager.has_feature

    def _bridged_has_feature(self, feature: str) -> bool:
        # Non-RWA features: full delegation to AG's existing logic
        # (plan check, expired-license read-only mode, etc.).
        if not (feature or "").startswith("rwa_"):
            return _orig_has_feature(self, feature)
        # RWA features: AG's logic might still say True if the cached
        # features list already contains the rwa_* id (rare today, will
        # be the production path once RWAGenie licenses are minted).
        if _orig_has_feature(self, feature):
            return True
        # Fall back to the tier-matched RWA bundle. Treats the user's
        # AG plan as if it were the equivalent RWAGenie plan.
        plan = (self.plan or "").upper()
        return feature in _RWA_FEATURES_BY_PLAN.get(plan, [])

    _lm.LicenseManager.has_feature = _bridged_has_feature
    _INSTALLED = True
