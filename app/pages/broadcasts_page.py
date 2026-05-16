"""
Broadcasts page — compose + persist messages.

v0.1 ships the composer + persistence + audience-resolver. Actual
delivery (email / SMS / WhatsApp) is wired up once the provider is
chosen. "Mark as sent" stamps sent_at + sent_count so admins keep
track of which messages went out.
"""
from __future__ import annotations

from PySide6.QtCore    import Qt, Signal
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QLineEdit,
    QTableWidget, QTableWidgetItem, QDialog, QFormLayout, QComboBox,
    QTextEdit, QMessageBox, QFrame,
)

from app.theme    import THEME
from app.services.broadcasts import (
    BroadcastsService, VALID_CHANNELS, VALID_AUDIENCES,
)
from app.pages._common import style_table, apply_text_filter


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

        # Channel hint — note that NONE means "persist only, no delivery"
        note = QLabel(
            "💡 Channel = None means the broadcast is saved here as a "
            "record but isn't actually sent anywhere. Email / SMS / "
            "WhatsApp delivery wires up once the provider account is "
            "set up. 'Mark as sent' on the list view stamps the row."
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


class BroadcastsPage(QWidget):
    def __init__(self, db, company_id: int, tree, parent=None):
        super().__init__(parent)
        self.svc = BroadcastsService(db, company_id)
        self._build_ui()
        self.refresh()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 16, 24, 24); layout.setSpacing(10)

        title = QLabel("Broadcasts")
        title.setObjectName("page_title")
        layout.addWidget(title)
        sub = QLabel(
            "Targeted messages — to all residents, owners only, tenants "
            "only, or selected flats. Email / SMS / WhatsApp delivery "
            "ships when the provider is set up; v0.1 persists the "
            "messages and the audience choice."
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

        sent_btn = QPushButton("Mark as sent"); sent_btn.setFixedHeight(30)
        sent_btn.clicked.connect(self._on_mark_sent)
        bar_l.addWidget(sent_btn)

        del_btn = QPushButton("Delete"); del_btn.setFixedHeight(30)
        del_btn.clicked.connect(self._on_delete)
        bar_l.addWidget(del_btn)

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

    def _on_mark_sent(self):
        bid = self._selected_id()
        if not bid:
            return
        bcast = self.svc.get(bid)
        if not bcast:
            return
        n = self.svc.resolve_audience_count(
            bcast.get("audience"), bcast.get("selected_flats")
        )
        if QMessageBox.question(
            self, "Mark as sent",
            f"Stamp this broadcast as sent to ~{n} recipients now? "
            f"(Actual delivery happens via the configured channel.)",
        ) != QMessageBox.StandardButton.Yes:
            return
        from datetime import datetime
        self.svc.update(
            bid,
            sent_at=datetime.utcnow().isoformat(timespec="seconds"),
            sent_count=n,
        )
        self.refresh()

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
        self.refresh()
