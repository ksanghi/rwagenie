"""
Cloud Sync page — bootstrap, sync now, sync status.

Single-page UX:
  • Top: enabled/disabled toggle + bootstrapped status
  • Activate cloud sync button (first-run bootstrap)
  • Sync now button (manual; auto-sync on a timer can come later)
  • Status: last pushed / last pulled timestamps
  • Server URL field (advanced)

The sync itself runs in a QThread — full snapshots can be slow.
"""
from __future__ import annotations

import logging
from typing import Optional

from PySide6.QtCore    import Qt, QThread, QObject, Signal
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QLineEdit,
    QFrame, QMessageBox, QCheckBox, QFormLayout,
)

from app.theme    import THEME
from app.services.cloud_sync import (
    CloudSyncService, CloudSyncError, NotBootstrapped, SyncReport,
)


logger = logging.getLogger(__name__)


class _SyncWorker(QObject):
    done = Signal(object, str)         # (SyncReport or None, err msg)

    def __init__(self, svc: CloudSyncService, action: str):
        super().__init__()
        self.svc = svc
        self.action = action            # "bootstrap" / "sync"

    def run(self):
        try:
            if self.action == "bootstrap":
                self.svc.bootstrap()
                self.done.emit(None, "")
            else:
                rep = self.svc.sync_all()
                err = "; ".join(rep.errors) if rep.errors else ""
                self.done.emit(rep, err)
        except CloudSyncError as e:
            self.done.emit(None, str(e))
        except Exception as e:
            logger.exception("sync worker crashed")
            self.done.emit(None, f"unexpected: {e}")


class CloudSyncPage(QWidget):
    def __init__(self, db, company_id: int, tree, parent=None):
        super().__init__(parent)
        self.db = db
        self.company_id = company_id
        self.svc = CloudSyncService(db, company_id, tree)
        self._thread: Optional[QThread] = None
        self._worker: Optional[_SyncWorker] = None
        self._build_ui()
        self.refresh()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 16, 24, 24); layout.setSpacing(12)

        title = QLabel("Cloud Sync")
        title.setObjectName("page_title")
        layout.addWidget(title)

        sub = QLabel(
            "Push flats / residents / notices / polls to "
            "<b>rwagenie-web</b> so residents can log in and use the "
            "web app. Resident-filed complaints flow back to the "
            "Complaints page here on each sync."
        )
        sub.setObjectName("page_subtitle")
        sub.setWordWrap(True)
        layout.addWidget(sub)

        # Status card
        self.status_card = QFrame()
        self.status_card.setObjectName("card")
        self.status_card.setStyleSheet(
            f"QFrame#card {{ background:{THEME.get('bg_hover','#334155')};"
            f" border-radius:8px; padding:14px; }}"
        )
        scl = QFormLayout(self.status_card)
        scl.setSpacing(6)

        self.lbl_status   = QLabel("…")
        self.lbl_status.setStyleSheet(f"font-weight:bold; color:{THEME['accent']};")
        scl.addRow(QLabel("Status:"),       self.lbl_status)

        self.lbl_server   = QLabel("…")
        scl.addRow(QLabel("Server:"),       self.lbl_server)

        self.lbl_slug     = QLabel("…")
        scl.addRow(QLabel("Society slug:"), self.lbl_slug)

        self.lbl_pushed   = QLabel("never")
        scl.addRow(QLabel("Last pushed:"),  self.lbl_pushed)

        self.lbl_pulled   = QLabel("never")
        scl.addRow(QLabel("Last pulled:"),  self.lbl_pulled)

        layout.addWidget(self.status_card)

        # Toggle
        self.chk_enabled = QCheckBox("Enable cloud sync for this society")
        self.chk_enabled.toggled.connect(self._on_toggle)
        layout.addWidget(self.chk_enabled)

        # Action buttons
        bar = QHBoxLayout()
        self.btn_bootstrap = QPushButton("🔑 Activate cloud sync")
        self.btn_bootstrap.setObjectName("btn_primary")
        self.btn_bootstrap.setFixedHeight(34)
        self.btn_bootstrap.clicked.connect(self._on_bootstrap)
        bar.addWidget(self.btn_bootstrap)

        self.btn_sync = QPushButton("⟲ Sync now")
        self.btn_sync.setFixedHeight(34)
        self.btn_sync.clicked.connect(self._on_sync_now)
        bar.addWidget(self.btn_sync)
        bar.addStretch()
        layout.addLayout(bar)

        # Advanced
        adv = QFrame(); adv.setObjectName("card")
        adv_l = QVBoxLayout(adv); adv_l.setContentsMargins(12, 8, 12, 8); adv_l.setSpacing(6)
        adv_l.addWidget(QLabel("<b>Advanced — Sync server URL</b>"))
        row = QHBoxLayout()
        self.url_edit = QLineEdit()
        self.url_edit.setFixedHeight(28)
        row.addWidget(self.url_edit)
        save_url = QPushButton("Save URL"); save_url.setFixedHeight(28)
        save_url.clicked.connect(self._on_save_url)
        row.addWidget(save_url)
        adv_l.addLayout(row)
        adv_l.addWidget(QLabel(
            "Defaults to https://rwagenie-web.fly.dev. Change only if "
            "you self-host the resident portal."
        ))
        layout.addWidget(adv)

        # Sync result panel
        self.result_label = QLabel("")
        self.result_label.setWordWrap(True)
        self.result_label.setStyleSheet(
            f"color:{THEME['text_secondary']}; font-size:11px; padding:8px;"
            f" background:{THEME.get('bg_hover','#334155')}; border-radius:6px;"
        )
        self.result_label.hide()
        layout.addWidget(self.result_label)

        layout.addStretch(1)

    def refresh(self) -> None:
        st = self.svc.status()
        self.chk_enabled.blockSignals(True)
        self.chk_enabled.setChecked(st["enabled"])
        self.chk_enabled.blockSignals(False)

        self.lbl_server.setText(st["server_url"])
        self.lbl_slug.setText(st["society_slug"])
        self.lbl_pushed.setText(st["last_pushed_at"] or "never")
        self.lbl_pulled.setText(st["last_pulled_at"] or "never")
        if st["bootstrapped"]:
            self.lbl_status.setText("✓ Bootstrapped — sync is ready")
            self.btn_bootstrap.setText("🔄 Re-activate cloud sync")
            self.btn_sync.setEnabled(st["enabled"])
        else:
            self.lbl_status.setText("⚠ Not bootstrapped yet — click Activate")
            self.btn_bootstrap.setText("🔑 Activate cloud sync")
            self.btn_sync.setEnabled(False)
        self.url_edit.setText(st["server_url"])

    def _on_toggle(self, checked: bool) -> None:
        self.svc.set_enabled(checked)
        self.refresh()

    def _on_save_url(self) -> None:
        self.svc.set_server_url(self.url_edit.text())
        self.refresh()
        QMessageBox.information(self, "Saved", "Sync server URL saved.")

    def _on_bootstrap(self) -> None:
        if self._thread is not None:
            return
        self._kick_worker("bootstrap")

    def _on_sync_now(self) -> None:
        if self._thread is not None:
            return
        self._kick_worker("sync")

    def _kick_worker(self, action: str) -> None:
        self.btn_bootstrap.setEnabled(False)
        self.btn_sync.setEnabled(False)
        self.result_label.setText(f"Running {action}…")
        self.result_label.show()

        self._thread = QThread(self)
        self._worker = _SyncWorker(self.svc, action)
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.done.connect(self._on_done)
        self._worker.done.connect(self._thread.quit)
        self._thread.finished.connect(self._worker.deleteLater)
        self._thread.finished.connect(self._thread.deleteLater)
        self._thread.start()

    def _on_done(self, report, err: str) -> None:
        self._thread = None
        self._worker = None

        if err and report is None:
            self.result_label.setText(f"❌ {err}")
            QMessageBox.critical(self, "Sync failed", err)
        elif report is None:
            self.result_label.setText("✓ Bootstrap done. Click Sync now to push society data.")
        else:
            r: SyncReport = report
            pushed = "  ·  ".join(f"{k}: {v}" for k, v in r.pushed.items()) or "(nothing pushed)"
            pulled = "  ·  ".join(f"{k}: {v}" for k, v in r.pulled.items()) or "(nothing new pulled)"
            warn = f"\n⚠ {err}" if err else ""
            self.result_label.setText(
                f"✓ Sync complete.\n"
                f"<b>Pushed:</b> {pushed}\n"
                f"<b>Pulled:</b> {pulled}"
                f"{warn}"
            )

        self.refresh()
