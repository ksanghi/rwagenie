"""
Audit log viewer — admin + auditor can see who changed what.

Read-only. Most-recent-first. Filterable by user, action keyword,
entity type, and a date floor. Selecting a row + clicking "Details"
opens a dialog with the before/after JSON for diff inspection.
"""
from __future__ import annotations

import json

from PySide6.QtCore    import Qt
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QLineEdit,
    QComboBox, QTableWidget, QTableWidgetItem, QDialog, QTextEdit,
    QFrame, QMessageBox,
)

from app.theme    import THEME
from app.services.audit import AuditLogService
from app.services.auth  import AuthSession
from app.pages._common  import style_table, apply_text_filter


class AuditLogPage(QWidget):
    def __init__(self, db, company_id: int, tree,
                 auth: AuthSession, parent=None):
        super().__init__(parent)
        self.db = db
        self.company_id = company_id
        self.auth = auth
        self.svc  = AuditLogService(db, company_id)
        self._build_ui()
        self.refresh()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 16, 24, 24); layout.setSpacing(10)

        title = QLabel("Audit log")
        title.setObjectName("page_title")
        layout.addWidget(title)

        sub = QLabel(
            "Every state-changing action by every signed-in user. "
            "Append-only — entries are never edited or deleted from "
            "inside the app."
        )
        sub.setObjectName("page_subtitle")
        layout.addWidget(sub)

        bar = QFrame(); bar.setObjectName("card")
        bar_l = QHBoxLayout(bar)
        bar_l.setContentsMargins(10, 6, 10, 6); bar_l.setSpacing(8)

        self.user_combo = QComboBox(); self.user_combo.setFixedHeight(30)
        self.user_combo.addItem("All users", "")
        for u in self.svc.distinct_users():
            self.user_combo.addItem(u, u)
        self.user_combo.currentIndexChanged.connect(self.refresh)
        bar_l.addWidget(self.user_combo)

        self.entity_combo = QComboBox(); self.entity_combo.setFixedHeight(30)
        self.entity_combo.addItems(
            ["All entities", "flat", "owner", "user", "notice",
             "complaint", "broadcast", "poll", "visitor"]
        )
        self.entity_combo.setItemData(0, "")
        for i in range(1, self.entity_combo.count()):
            self.entity_combo.setItemData(i, self.entity_combo.itemText(i))
        self.entity_combo.currentIndexChanged.connect(self.refresh)
        bar_l.addWidget(self.entity_combo)

        self.action_edit = QLineEdit()
        self.action_edit.setPlaceholderText("Action contains…")
        self.action_edit.setFixedHeight(30)
        self.action_edit.setClearButtonEnabled(True)
        self.action_edit.textChanged.connect(self.refresh)
        bar_l.addWidget(self.action_edit, 2)

        self.filter_edit = QLineEdit()
        self.filter_edit.setPlaceholderText("🔍 Quick filter rows…")
        self.filter_edit.setFixedHeight(30)
        self.filter_edit.setClearButtonEnabled(True)
        self.filter_edit.textChanged.connect(
            lambda t: apply_text_filter(self.table, t)
        )
        bar_l.addWidget(self.filter_edit, 2)

        refresh_btn = QPushButton("Reload"); refresh_btn.setFixedHeight(30)
        refresh_btn.clicked.connect(self.refresh)
        bar_l.addWidget(refresh_btn)

        details = QPushButton("Details"); details.setFixedHeight(30)
        details.clicked.connect(self._on_details)
        bar_l.addWidget(details)

        layout.addWidget(bar)

        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(
            ["When", "User", "Action", "Entity", "ID", "Summary"]
        )
        style_table(self.table, stretch_cols=[5])
        self.table.doubleClicked.connect(self._on_details)
        layout.addWidget(self.table, 1)

        self.summary = QLabel("")
        self.summary.setStyleSheet(
            f"color:{THEME['text_secondary']}; font-size:11px; padding:4px;"
        )
        layout.addWidget(self.summary)

    def refresh(self):
        rows = self.svc.list(
            limit=1000,
            action_substr=self.action_edit.text().strip(),
            username=self.user_combo.currentData() or "",
            entity_type=self.entity_combo.currentData() or "",
        )
        self.table.setSortingEnabled(False)
        self.table.setRowCount(len(rows))
        for r, e in enumerate(rows):
            when = QTableWidgetItem(e.get("at") or "")
            when.setData(Qt.ItemDataRole.UserRole, e["id"])
            self.table.setItem(r, 0, when)
            self.table.setItem(r, 1, QTableWidgetItem(e.get("username") or "—"))
            self.table.setItem(r, 2, QTableWidgetItem(e.get("action") or ""))
            self.table.setItem(r, 3, QTableWidgetItem(e.get("entity_type") or ""))
            self.table.setItem(r, 4, QTableWidgetItem(
                str(e["entity_id"]) if e.get("entity_id") is not None else ""
            ))
            self.table.setItem(r, 5, QTableWidgetItem(e.get("summary") or ""))
        self.table.setSortingEnabled(True)
        apply_text_filter(self.table, self.filter_edit.text())
        self.summary.setText(
            f"{len(rows)} entries shown" + (
                "  (capped at 1000 — narrow filters for older history)"
                if len(rows) == 1000 else ""
            )
        )

    def _on_details(self, *_):
        row = self.table.currentRow()
        if row < 0:
            QMessageBox.information(self, "Pick a row",
                                    "Select a row, then click Details.")
            return
        item = self.table.item(row, 0)
        log_id = item.data(Qt.ItemDataRole.UserRole) if item else None
        if not log_id: return
        rec = self.svc.detail(log_id)
        if not rec: return
        _DetailDialog(rec, parent=self).exec()


class _DetailDialog(QDialog):
    def __init__(self, rec: dict, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Audit log — details")
        self.setMinimumSize(620, 460)
        self.setModal(True)

        v = QVBoxLayout(self); v.setContentsMargins(16, 16, 16, 16); v.setSpacing(8)

        hdr = QLabel(
            f"<b>{rec.get('action','')}</b>  ·  "
            f"{rec.get('username','—')}  ·  "
            f"{rec.get('at','')}"
        )
        hdr.setStyleSheet(
            f"font-size:13px; color:{THEME['accent']};"
        )
        v.addWidget(hdr)

        meta = QLabel(
            f"Entity: <b>{rec.get('entity_type','—')}</b>  ·  "
            f"ID: <b>{rec.get('entity_id') if rec.get('entity_id') is not None else '—'}</b>  ·  "
            f"Summary: {rec.get('summary','')}"
        )
        meta.setStyleSheet(f"color:{THEME['text_secondary']}; font-size:11px;")
        meta.setWordWrap(True)
        v.addWidget(meta)

        v.addWidget(QLabel("Before:"))
        before = QTextEdit(_pretty(rec.get("before_json")))
        before.setReadOnly(True)
        v.addWidget(before, 1)

        v.addWidget(QLabel("After:"))
        after = QTextEdit(_pretty(rec.get("after_json")))
        after.setReadOnly(True)
        v.addWidget(after, 1)

        close = QPushButton("Close"); close.clicked.connect(self.accept)
        row = QHBoxLayout(); row.addStretch(); row.addWidget(close)
        v.addLayout(row)


def _pretty(json_text: str | None) -> str:
    if not json_text:
        return "(none)"
    try:
        return json.dumps(json.loads(json_text), indent=2, ensure_ascii=False)
    except Exception:
        return json_text
