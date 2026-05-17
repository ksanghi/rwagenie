"""
Broadcasts page — compose + persist + actually send (v0.1.2+).

Channel = None still means persist-only. EMAIL / SMS now dispatch
through BroadcastSendService in a background thread (UI freezes
otherwise for sends > a handful of recipients). A per-recipient log
goes into rwa_broadcast_recipients so the admin can see who got it
and who bounced.
"""
from __future__ import annotations

from PySide6.QtCore    import Qt, Signal, QThread, QObject
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QLineEdit,
    QTableWidget, QTableWidgetItem, QDialog, QFormLayout, QComboBox,
    QTextEdit, QMessageBox, QFrame, QProgressDialog,
)

from app.theme    import THEME
from app.services.broadcasts import (
    BroadcastsService, VALID_CHANNELS, VALID_AUDIENCES,
)
from app.services.broadcast_send import BroadcastSendService, SendResult
from app.pages._common               import style_table, apply_text_filter
from app.pages._audit_hooks          import page_audit
from app.pages.broadcast_settings_dialog import BroadcastSettingsDialog


# ── Composer dialog (unchanged from v0.1) ──────────────────────────────

class _BroadcastDialog(QDialog):
    saved = Signal()

    def __init__(self, service: BroadcastsService, bid: int | None = None,
                 parent=None):
        super().__init__(parent)
        self.svc = service
        self.bid = bid
        self._existing = service.get(bid) if bid else None

        self.setWindowTitle("Edit Broadcast" if bid else "New Broadcast")
        self.setMinimumWidth(540)
        self.setModal(True)

        layout = QVBoxLayout(self); layout.setSpacing(10)
        layout.setContentsMargins(20, 20, 20, 20)

        hdr = QLabel("✎ Edit Broadcast" if self._existing else "+ New Broadcast")
        hdr.setStyleSheet(
            f"font-size:14px; font-weight:bold; color:{THEME['accent']};"
        )
        layout.addWidget(hdr)

        form = QFormLayout(); form.setSpacing(8)
        e = self._existing or {}

        self.subject = QLineEdit(e.get("subject") or "")
        self.subject.setFixedHeight(32)
        self.subject.setPlaceholderText("e.g. Water tank cleaning on Sunday")
        form.addRow(QLabel("Subject *"), self.subject)

        self.body = QTextEdit(e.get("body") or "")
        self.body.setFixedHeight(140)
        self.body.setPlaceholderText("Message body.")
        form.addRow(QLabel("Message"), self.body)

        self.channel = QComboBox(); self.channel.setFixedHeight(32)
        for ch in VALID_CHANNELS:
            self.channel.addItem(ch.title(), ch)
        self._select_combo(self.channel, e.get("channel") or "NONE")
        form.addRow(QLabel("Channel"), self.channel)

        self.audience = QComboBox(); self.audience.setFixedHeight(32)
        for a in VALID_AUDIENCES:
            self.audience.addItem(a.title(), a)
        self._select_combo(self.audience, e.get("audience") or "ALL")
        self.audience.currentIndexChanged.connect(self._update_audience_count)
        form.addRow(QLabel("Audience"), self.audience)

        self.selected_flats = QLineEdit(e.get("selected_flats") or "")
        self.selected_flats.setFixedHeight(32)
        self.selected_flats.setPlaceholderText(
            "Comma-separated flat IDs (only when audience = Selected)"
        )
        form.addRow(QLabel("Selected flats"), self.selected_flats)

        self.audience_count = QLabel("")
        self.audience_count.setStyleSheet(
            f"color:{THEME['text_secondary']}; font-size:11px;"
        )
        form.addRow("", self.audience_count)

        layout.addLayout(form)

        note = QLabel(
            "💡 Channel = None means the broadcast is saved but not "
            "delivered. Pick Email or SMS, then use <b>Send Now</b> on "
            "the list to dispatch. WhatsApp is not implemented yet."
        )
        note.setWordWrap(True)
        note.setStyleSheet(
            f"color:{THEME['text_secondary']}; font-size:10px;"
            f" background:{THEME.get('bg_hover','#334155')};"
            f" padding:8px; border-radius:6px;"
        )
        layout.addWidget(note)

        btn_row = QHBoxLayout(); btn_row.addStretch()
        cancel = QPushButton("Cancel"); cancel.clicked.connect(self.reject)
        save   = QPushButton("Save"); save.setObjectName("btn_primary")
        save.clicked.connect(self._save)
        btn_row.addWidget(cancel); btn_row.addWidget(save)
        layout.addLayout(btn_row)

        self._update_audience_count()

    @staticmethod
    def _select_combo(combo: QComboBox, value):
        for i in range(combo.count()):
            if combo.itemData(i) == value:
                combo.setCurrentIndex(i); return

    def _update_audience_count(self, *_):
        try:
            n = self.svc.resolve_audience_count(
                self.audience.currentData(),
                self.selected_flats.text().strip() or None,
            )
            self.audience_count.setText(
                f"Estimated recipients: {n}" if n else "No recipients matched yet."
            )
        except Exception:
            self.audience_count.setText("")

    def _save(self):
        for w in (self.subject, self.selected_flats):
            try: w.clearFocus()
            except Exception: pass

        kw = dict(
            subject=self.subject.text().strip(),
            body=self.body.toPlainText().strip(),
            channel=self.channel.currentData(),
            audience=self.audience.currentData(),
            selected_flats=self.selected_flats.text().strip() or None,
        )
        try:
            if self.bid:
                self.svc.update(self.bid, **kw)
            else:
                self.svc.add(**kw)
        except ValueError as e:
            QMessageBox.warning(self, "Cannot save", str(e))
            return
        self.saved.emit()
        self.accept()


# ── Background send worker ─────────────────────────────────────────────

class _SendWorker(QObject):
    """Runs BroadcastSendService.send() off the Qt thread.

    Two signals back to the page:
      progress(done, total, name) — fires after each recipient
      finished(result_or_none, error_msg_or_empty) — fires once at end

    `result_or_none` is the SendResult on success, None on hard failure
    (e.g. SMTP login refused before any recipient was even tried).
    """
    progress = Signal(int, int, str)
    finished = Signal(object, str)

    def __init__(self, send_svc: BroadcastSendService, broadcast_id: int):
        super().__init__()
        self.send_svc     = send_svc
        self.broadcast_id = broadcast_id

    def run(self) -> None:
        try:
            res = self.send_svc.send(
                self.broadcast_id,
                on_progress=lambda done, total, name:
                    self.progress.emit(done, total, name),
            )
            self.finished.emit(res, "")
        except Exception as e:
            self.finished.emit(None, str(e))


# ── Page ───────────────────────────────────────────────────────────────

class BroadcastsPage(QWidget):
    def __init__(self, db, company_id: int, tree, parent=None):
        super().__init__(parent)
        self.db = db
        self.company_id = company_id
        self.svc      = BroadcastsService(db, company_id)
        self.send_svc = BroadcastSendService(db, company_id)
        self._build_ui()
        self.refresh()

        # Holders so the GC doesn't kill an in-flight send.
        self._thread:   QThread | None = None
        self._worker:   _SendWorker | None = None
        self._progress: QProgressDialog | None = None

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 16, 24, 24); layout.setSpacing(10)

        title = QLabel("Broadcasts")
        title.setObjectName("page_title")
        layout.addWidget(title)
        sub = QLabel(
            "Targeted messages — to all residents, owners only, tenants "
            "only, or selected flats. Email + SMS go live as soon as you "
            "set credentials under ⚙ Settings."
        )
        sub.setObjectName("page_subtitle")
        layout.addWidget(sub)

        bar = QFrame(); bar.setObjectName("card")
        bar_l = QHBoxLayout(bar)
        bar_l.setContentsMargins(10, 6, 10, 6); bar_l.setSpacing(8)

        self.filter_edit = QLineEdit()
        self.filter_edit.setPlaceholderText("🔍 Filter by subject / body…")
        self.filter_edit.setFixedHeight(30)
        self.filter_edit.setClearButtonEnabled(True)
        self.filter_edit.textChanged.connect(
            lambda t: apply_text_filter(self.table, t)
        )
        bar_l.addWidget(self.filter_edit, 3)

        add_btn = QPushButton("+ New Broadcast")
        add_btn.setObjectName("btn_primary"); add_btn.setFixedHeight(30)
        add_btn.clicked.connect(self._on_add)
        bar_l.addWidget(add_btn)

        edit_btn = QPushButton("Edit"); edit_btn.setFixedHeight(30)
        edit_btn.clicked.connect(self._on_edit)
        bar_l.addWidget(edit_btn)

        send_btn = QPushButton("📤 Send Now")
        send_btn.setObjectName("btn_primary"); send_btn.setFixedHeight(30)
        send_btn.clicked.connect(self._on_send_now)
        bar_l.addWidget(send_btn)

        log_btn = QPushButton("Delivery log"); log_btn.setFixedHeight(30)
        log_btn.clicked.connect(self._on_view_log)
        bar_l.addWidget(log_btn)

        del_btn = QPushButton("Delete"); del_btn.setFixedHeight(30)
        del_btn.clicked.connect(self._on_delete)
        bar_l.addWidget(del_btn)

        settings_btn = QPushButton("⚙ Settings"); settings_btn.setFixedHeight(30)
        settings_btn.clicked.connect(self._on_settings)
        bar_l.addWidget(settings_btn)

        layout.addWidget(bar)

        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels([
            "Subject", "Channel", "Audience", "Sent at", "Recipients", "Created",
        ])
        style_table(self.table, stretch_cols=[0])
        self.table.doubleClicked.connect(self._on_edit)
        layout.addWidget(self.table, 1)

        self.summary = QLabel("")
        self.summary.setStyleSheet(
            f"color:{THEME['text_secondary']}; font-size:11px; padding:4px;"
        )
        layout.addWidget(self.summary)

    def refresh(self):
        self.table.setSortingEnabled(False)
        rows = self.svc.list()
        self.table.setRowCount(len(rows))
        for r, b in enumerate(rows):
            subj = QTableWidgetItem(b.get("subject") or "")
            subj.setData(Qt.ItemDataRole.UserRole, b["id"])
            self.table.setItem(r, 0, subj)
            self.table.setItem(r, 1, QTableWidgetItem(
                (b.get("channel") or "NONE").title()
            ))
            self.table.setItem(r, 2, QTableWidgetItem(
                (b.get("audience") or "ALL").title()
            ))
            self.table.setItem(r, 3, QTableWidgetItem(b.get("sent_at") or "—"))
            self.table.setItem(r, 4, QTableWidgetItem(
                str(b.get("sent_count") or 0)
            ))
            self.table.setItem(r, 5, QTableWidgetItem(
                (b.get("created_at") or "").split(" ")[0]
            ))
        self.table.setSortingEnabled(True)
        apply_text_filter(self.table, self.filter_edit.text())
        sent = sum(1 for b in rows if b.get("sent_at"))
        self.summary.setText(
            f"{len(rows)} broadcast(s)  ·  {sent} sent  ·  {len(rows) - sent} draft"
        )

    def _selected_id(self) -> int | None:
        row = self.table.currentRow()
        if row < 0: return None
        item = self.table.item(row, 0)
        return item.data(Qt.ItemDataRole.UserRole) if item else None

    # ── Action handlers ────────────────────────────────────────────────

    def _on_add(self):
        dlg = _BroadcastDialog(self.svc, parent=self)
        dlg.saved.connect(self.refresh)
        dlg.exec()

    def _on_edit(self, *_):
        bid = self._selected_id()
        if not bid:
            QMessageBox.information(self, "No broadcast selected",
                                    "Pick a row first, then click Edit.")
            return
        dlg = _BroadcastDialog(self.svc, bid=bid, parent=self)
        dlg.saved.connect(self.refresh)
        dlg.exec()

    def _on_settings(self):
        dlg = BroadcastSettingsDialog(self.db, self.company_id, parent=self)
        dlg.exec()

    def _on_send_now(self):
        if self._thread is not None:
            QMessageBox.information(self, "Send in progress",
                                    "Another broadcast is already sending. "
                                    "Wait for it to finish.")
            return
        bid = self._selected_id()
        if not bid:
            QMessageBox.information(self, "No broadcast selected",
                                    "Pick a row first, then click Send Now.")
            return
        bcast = self.svc.get(bid)
        if not bcast:
            return
        channel = (bcast.get("channel") or "NONE").upper()
        if channel == "NONE":
            QMessageBox.warning(
                self, "No channel",
                "This broadcast has channel = None. Edit it and pick "
                "Email or SMS first.",
            )
            return
        if channel == "WHATSAPP":
            QMessageBox.warning(self, "Not supported",
                                "WhatsApp delivery isn't implemented yet.")
            return

        n = self.svc.resolve_audience_count(
            bcast.get("audience"), bcast.get("selected_flats")
        )
        if n == 0:
            QMessageBox.information(
                self, "No recipients",
                "Audience resolved to zero recipients — nothing to send.",
            )
            return
        if QMessageBox.question(
            self, "Send broadcast",
            f"Send '{bcast['subject']}' via {channel.title()} to ~{n} "
            f"recipient(s) now?",
        ) != QMessageBox.StandardButton.Yes:
            return

        # Progress dialog drives off the worker's progress signal.
        self._progress = QProgressDialog(
            "Sending…", "Cancel send (after current recipient)",
            0, max(n, 1), self,
        )
        self._progress.setWindowTitle("Broadcast")
        self._progress.setMinimumDuration(0)
        self._progress.setAutoClose(False)
        self._progress.setAutoReset(False)
        self._progress.setModal(True)
        # Hide the Cancel button — SMTP/HTTP calls don't easily abort
        # mid-call, so cancel is misleading. (v0.1.2: dropped; if we
        # add it later it'd flip a worker flag checked between
        # recipients.)
        self._progress.setCancelButton(None)
        self._progress.show()

        self._last_send_bid = bid

        self._thread = QThread(self)
        self._worker = _SendWorker(self.send_svc, bid)
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.progress.connect(self._on_send_progress)
        self._worker.finished.connect(self._on_send_finished)
        # Cleanup chain.
        self._worker.finished.connect(self._thread.quit)
        self._thread.finished.connect(self._worker.deleteLater)
        self._thread.finished.connect(self._thread.deleteLater)
        self._thread.start()

    def _on_send_progress(self, done: int, total: int, name: str) -> None:
        if self._progress is None:
            return
        self._progress.setMaximum(max(total, 1))
        self._progress.setValue(done)
        self._progress.setLabelText(f"Sent to {done}/{total}\nLast: {name}")

    def _on_send_finished(self, result: SendResult | None, error: str) -> None:
        if self._progress is not None:
            self._progress.close()
            self._progress = None
        self._thread = None
        self._worker = None

        if error:
            QMessageBox.critical(
                self, "Send failed",
                f"Broadcast send failed before any recipient was reached:\n\n"
                f"{error}\n\n"
                f"Common causes:\n"
                f"• SMTP / Fast2SMS credentials wrong (open ⚙ Settings)\n"
                f"• No internet connectivity\n"
                f"• Fast2SMS account out of credits",
            )
            self.refresh()
            return

        assert result is not None
        # Audit log: who sent what, to how many, with what outcome.
        # `_last_send_bid` is set in _on_send_now before the worker
        # starts so we still know the broadcast id here.
        bid = getattr(self, "_last_send_bid", None)
        if bid is not None:
            bcast = self.svc.get(bid) or {}
            page_audit(
                self, action="send_broadcast",
                entity_type="broadcast", entity_id=bid,
                summary=f"{bcast.get('subject','')} · "
                        f"{result.sent} sent / {result.failed} failed / "
                        f"{result.skipped} skipped",
                after={
                    "channel":  bcast.get("channel"),
                    "audience": bcast.get("audience"),
                    "sent":     result.sent,
                    "failed":   result.failed,
                    "skipped":  result.skipped,
                },
            )

        msg = (
            f"✓ Sent:    {result.sent}\n"
            f"✗ Failed:  {result.failed}\n"
            f"⊘ Skipped: {result.skipped}  (no contact on record)\n"
        )
        if result.errors:
            sample = "\n".join(f"  • {e}" for e in result.errors[:5])
            extra = "" if len(result.errors) <= 5 else (
                f"\n  …and {len(result.errors) - 5} more (see Delivery log)"
            )
            msg += f"\nFailures:\n{sample}{extra}"

        QMessageBox.information(self, "Broadcast complete", msg)
        self.refresh()

    def _on_view_log(self) -> None:
        bid = self._selected_id()
        if not bid:
            QMessageBox.information(self, "No broadcast selected",
                                    "Pick a row first, then click Delivery log.")
            return
        _DeliveryLogDialog(self.db, bid, parent=self).exec()

    def _on_delete(self):
        bid = self._selected_id()
        if not bid:
            return
        b = self.svc.get(bid)
        if QMessageBox.question(
            self, "Delete broadcast",
            f"Delete '{b.get('subject','')}'? This can't be undone.",
        ) != QMessageBox.StandardButton.Yes:
            return
        self.svc.delete(bid)
        page_audit(
            self, action="delete_broadcast",
            entity_type="broadcast", entity_id=bid,
            summary=b.get("subject") or "",
        )
        self.refresh()


# ── Delivery log dialog ────────────────────────────────────────────────

class _DeliveryLogDialog(QDialog):
    """Read-only per-recipient delivery view for one broadcast."""

    def __init__(self, db, broadcast_id: int, parent=None):
        super().__init__(parent)
        self.db = db
        self.bid = broadcast_id
        self.setWindowTitle("Delivery log")
        self.setMinimumSize(720, 420)
        self.setModal(True)

        v = QVBoxLayout(self)
        v.setContentsMargins(16, 16, 16, 16); v.setSpacing(8)

        bcast = self.db.execute(
            "SELECT subject, channel FROM rwa_broadcasts WHERE id=?",
            (broadcast_id,),
        ).fetchone()
        title = QLabel(f"📋 {bcast['subject'] if bcast else '?'}  ·  "
                       f"{(bcast['channel'] if bcast else '').title()}")
        title.setStyleSheet(
            f"font-size:14px; font-weight:bold; color:{THEME['accent']};"
        )
        v.addWidget(title)

        rows = self.db.execute(
            """SELECT r.address, r.status, r.error, r.attempted_at,
                      COALESCE(o.name,'(unknown)') AS owner
                 FROM rwa_broadcast_recipients r
                 LEFT JOIN rwa_owners o ON o.id = r.owner_id
                WHERE r.broadcast_id=?
                ORDER BY r.id""",
            (broadcast_id,),
        ).fetchall()

        table = QTableWidget(len(rows), 5)
        table.setHorizontalHeaderLabels(
            ["Recipient", "Address", "Status", "Error", "Attempted at"]
        )
        style_table(table, stretch_cols=[3])
        for i, r in enumerate(rows):
            table.setItem(i, 0, QTableWidgetItem(r["owner"]))
            table.setItem(i, 1, QTableWidgetItem(r["address"] or ""))
            table.setItem(i, 2, QTableWidgetItem(r["status"]))
            table.setItem(i, 3, QTableWidgetItem(r["error"] or ""))
            table.setItem(i, 4, QTableWidgetItem(r["attempted_at"] or ""))
        v.addWidget(table, 1)

        counts: dict[str, int] = {}
        for r in rows:
            counts[r["status"]] = counts.get(r["status"], 0) + 1
        summary = QLabel("  ·  ".join(
            f"{k}: {v_}" for k, v_ in counts.items()
        ) or "No attempts recorded yet.")
        summary.setStyleSheet(
            f"color:{THEME['text_secondary']}; font-size:11px;"
        )
        v.addWidget(summary)

        close = QPushButton("Close"); close.clicked.connect(self.accept)
        row = QHBoxLayout(); row.addStretch(); row.addWidget(close)
        v.addLayout(row)
