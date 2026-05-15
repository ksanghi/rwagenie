"""
RWAGenie launcher (the real one, after main.py bootstraps sys.path).

Reuses AccGenie's CompanyDialog for company create/open, then shows
our RWAMainWindow instead of AG's plain MainWindow. Everything else
(license startup re-validate, install heartbeat) is inherited from
AG's main module via direct reuse.
"""
from __future__ import annotations

import os
import sys
import threading
from pathlib import Path

from PySide6.QtWidgets import QApplication, QDialog
from PySide6.QtGui     import QIcon

from app                import PRODUCT_NAME, __version__
from app.theme          import get_stylesheet
from app.main_window    import RWAMainWindow

# Dev-time bridge: let the user's AG license unlock the matching RWA
# feature tier inside RWAGenie. Remove this once the server can mint
# product='rwagenie' keys end-to-end and the desktop walks the user
# through entering an RWAGenie key on first run.
from app.license_bridge import install as _install_license_bridge


def main() -> int:
    _install_license_bridge()

    app = QApplication(sys.argv)
    app.setApplicationName(PRODUCT_NAME)
    app.setApplicationVersion(__version__)
    app.setOrganizationName("Aiccounting")
    app.setStyle("Fusion")
    app.setStyleSheet(get_stylesheet())

    # Anonymous install heartbeat — fire-and-forget on a background thread,
    # same pattern as AG. Reports product='rwagenie' so server-side stats
    # show RWAGenie installs distinctly.
    try:
        from core.telemetry import send_install_heartbeat
        send_install_heartbeat()  # AG's heartbeat doesn't know product yet;
        # this'll mark them all 'accgenie' until we extend the heartbeat
        # payload in a follow-up.
    except Exception:
        pass

    # Silent license re-validate in the background.
    try:
        from core.license_manager import LicenseManager
        threading.Thread(
            target=lambda: LicenseManager().validate_on_startup(),
            daemon=True,
        ).start()
    except Exception:
        pass

    # RWAGenie's own CompanyDialog (parallel to AG's but branded for
    # societies). Importing AG's would collide with rwagenie/main.py on
    # sys.path — kept separate so both repos own their entry-screen UX.
    from app.company_dialog import CompanyDialog
    dlg = CompanyDialog()
    if dlg.exec() != QDialog.DialogCode.Accepted:
        return 0

    db         = dlg.selected_db
    company_id = dlg.selected_cid
    tree       = dlg.selected_tree

    from core.voucher_engine import VoucherEngine
    engine = VoucherEngine(db, company_id)

    window = RWAMainWindow(db, company_id, tree, engine)
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main() or 0)
