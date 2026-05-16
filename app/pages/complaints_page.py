"""
Complaints page — maintenance / civic tickets raised by residents.

Status workflow: OPEN → IN_PROGRESS → RESOLVED → CLOSED. Priorities
URGENT / HIGH / NORMAL / LOW. The list sorts open + urgent items to
the top so admins always see what's blocking first.
"""
from __future__ import annotations

from PySide6.QtCore    import Qt, Signal
from PySide6.QtGui     import QColor
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QLineEdit,
    QTableWidget, QTableWidgetItem, QDialog, QFormLayout, QComboBox,
    QTextEdit, QMessageBox, QFrame,
)

from app.theme    import THEME
from app.services.complaints import (
    ComplaintsService, VALID_CATEGORIES, VALID_PRIORITIES, VALID_STATUSES,
)
from app.services import FlatsService, OwnersService
from app.pages._common import style_table, apply_text_filter


_PRIORITY_COLORS = {
    "URGENT": "danger",
    "HIGH":   "warning",
    "NORMAL": "text_primary",
    "LOW":    "text_secondary",
}
_STATUS_COLORS = {
    "OPEN":         "warning",
    "IN_PROGRESS":  "accent",
    "RESOLVED":     "success",
    "CLOSED":       "text_dim",
}


class _ComplaintDialog(QDialog):
    saved = Signal()

    def __init__(self, complaints: ComplaintsService,
                 flats: FlatsService, owners: OwnersService,
                 complaint_id: int | None = None, parent=None):
        super().__init__(parent)
        self.svc      = complaints
        self.flats    = flats
        self.owners   = owners
        self.complaint_id = complaint_id
        self._existing = complaints.get(complaint_id) if complaint_id else None

        self.setWindowTitle("Edit Complaint" if complaint_id else "New Complaint")
        self.setMinimumWidth(540)
        self.setModal(True)

        layout = QVBoxLayout(self); layout.setSpacing(10)
        layout.setContentsMargins(20, 20, 20, 20)

        hdr = QLabel("✎ Edit Complaint" if self._existing else "+ New Complaint")
        hdr.setStyleSheet(
            f"font-size:14px; font-weight:bold; color:{THEME['accent']};"
        )
        layout.addWidget(hdr)

        form = QFormLayout(); form.setSpacing(8)
        e = self._existing or {}

        # Flat picker
        self.flat = QComboBox(); self.flat.setFixedHeight(32)
        self.flat.addItem("(no flat)", None)
        for f in self.flats.list_flats(active_only=True):
            self.flat.addItem(f["flat_no"], f["id"])
        if e.get("flat_id"):
            self._select_combo(self.flat, e["flat_id"])
        form.addRow(QLabel("Flat"), self.flat)

        # Raised-by picker
        self.raised_by = QComboBox(); self.raised_by.setFixedHeight(32)
        self.raised_by.addItem("(not recorded)", None)
        for o in self.owners.list_owners(active_only=True):
            self.raised_by.addItem(o["name"], o["id"])
        if e.get("raised_by_owner"):
            self._select_combo(self.raised_by, e["raised_by_owner"])
        form.addRow(QLabel("Raised by"), self.raised_by)

        self.title = QLineEdit(e.get("title") or "")
        self.title.setFixedHeight(32)
        self.title.setPlaceholderText("e.g. Leaking tap in master bedroom")
        form.addRow(QLabel("Title *"), self.title)

        self.category = QComboBox(); self.category.setFixedHeight(32)
        for c in VALID_CATEGORIES:
            self.category.addItem(c.title(), c)
        if e.get("category"):
            self._select_combo(self.category, e["category"])
        form.addRow(QLabel("Category"), self.category)

        self.priority = QComboBox(); self.priority.setFixedHeight(32)
        for p in VALID_PRIORITIES:
            self.priority.addItem(p.title(), p)
        self._select_combo(self.priority, e.get("priority") or "NORMAL")
        form.addRow(QLabel("Priority"), self.priority)

        self.description = QTextEdit(e.get("description") or "")
        self.description.setFixedHeight(80)
        self.description.setPlaceholderText("What happened, when, any photos sent separately, etc.")
        form.addRow(QLabel("Description"), self.description)

        self.status = QComboBox(); self.status.setFixedHeight(32)
        for s in VALID_STATUSES:
            self.status.addItem(s.replace("_", " ").title(), s)
        self._select_combo(self.status, e.get("status") or "OPEN")
        form.addRow(QLabel("Status"), self.status)

        self.assigned_to = QLineEdit(e.get("assigned_to") or "")
        self.assigned_to.setFixedHeight(32)
        self.assigned_to.setPlaceholderText("Plumber name / vendor / committee member")
        form.addRow(QLabel("Assigned to"), self.assigned_to)

        self.resolution = QTextEdit(e.get("resolution_notes") or "")
        self.resolution.setFixedHeight(60)
        self.resolution.setPlaceholderText(
            "How it was fixed (fill in when status moves to Resolved)"
        )
        form.addRow(QLabel("Resolution notes"), self.resolution)

        layout.addLayout(form)

        btn_row = QHBoxLayout(); btn_row.addStretch()
        cancel = QPushButton("Cancel"); cancel.clicked.connect(self.reject)
        save   = QPushButton("Save"); save.setObjectName("btn_primary")
        save.clicked.connect(self._save)
        btn_row.addWidget(cancel); btn_row.addWidget(save)
        layout.addLayout(btn_row)

    @staticmethod
    def _select_combo(combo: QComboBox, value):
        for i in range(combo.count()):
            if combo.itemData(i) == value:
                combo.setCurrentIndex(i); return

    def _save(self):
        for w in (self.title, self.assigned_to):
            try: w.clearFocus()
            except Exception: pass
        kw = dict(
            flat_id=self.flat.currentData(),
            raised_by_owner=self.raised_by.currentData(),
            title=self.title.text().strip(),
            category=self.category.currentData(),
            priority=self.priority.currentData(),
            description=self.description.toPlainText().strip(),
            assigned_to=self.assigned_to.text().strip(),
            resolution_notes=self.resolution.toPlainText().strip(),
        )
        try:
            if self.complaint_id:
                # Status comes through update too
                kw["status"] = self.status.currentData()
                self.svc.update(self.complaint_id, **kw)
            else:
                # Add path uses defaults for status (OPEN) inside service.
                kw.pop("status", None)
                kw.pop("resolution_notes", None)
                self.svc.add(**kw)
        except ValueError as e:
            QMessageBox.warning(self, "Cannot save", str(e))
            return
        self.saved.emit()
        self.accept()


class ComplaintsPage(QWidget):
    """Master list of complaints with status filter, search, and a
    header-card showing open/in-progress/urgent counters."""

    def __init__(self, db, company_id: int, tree, parent=None):
        super().__init__(parent)
        self.svc    = ComplaintsService(db, company_id)
        self.flats  = FlatsService(db, company_id, tree)
        self.owners = OwnersService(db, company_id)
        self._build_ui()
        self.refresh()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 16, 24, 24); layout.setSpacing(10)

        title = QLabel("Complaints")
        title.setObjectName("page_title")
        layout.addWidget(title)
        sub = QLabel(
            "Maintenance / civic tickets raised by residents. Open + urgent "
            "items float to the top."
        )
        sub.setObjectName("page_subtitle")
        layout.addWidget(sub)

        # Header counters
        self.counters = QLabel("")
        self.counters.setStyleSheet(
            f"color:{THEME['text_secondary']}; font-size:12px; padding:6px 4px;"
        )
        layout.addWidget(self.counters)

        # Toolbar
        bar = QFrame(); bar.setObjectName("card")
        bar_l = QHBoxLayout(bar)
        bar_l.setContentsMargins(10, 6, 10, 6); bar_l.setSpacing(8)

        self.filter_edit = QLineEdit()
        self.filter_edit.setPlaceholderText(
            "🔍 Filter by flat / title / category / assignee…"
        )
        self.filter_edit.setFixedHeight(30)
        self.filter_edit.setClearButtonEnabled(True)
        self.filter_edit.textChanged.connect(
            lambda t: apply_text_filter(self.table, t)
        )
        bar_l.addWidget(self.filter_edit, 3)

        self.status_filter = QComboBox(); self.status_filter.setFixedHeight(30)
        self.status_filter.addItem("All statuses", None)
        for s in VALID_STATUSES:
            self.status_filter.addItem(s.replace("_", " ").title(), s)
        self.status_filter.currentIndexChanged.connect(lambda _: self.refresh())
        bar_l.addWidget(self.status_filter)

        add_btn = QPushButton("+ New Complaint")
        add_btn.setObjectName("btn_primary"); add_btn.setFixedHeight(30)
        add_btn.clicked.connect(self._on_add)
        bar_l.addWidget(add_btn)

        edit_btn = QPushButton("Edit"); edit_btn.setFixedHeight(30)
        edit_btn.clicked.connect(self._on_edit)
        bar_l.addWidget(edit_btn)

        del_btn = QPushButton("Delete"); del_btn.setFixedHeight(30)
        del_btn.clicked.connect(self._on_delete)
        bar_l.addWidget(del_btn)

        layout.addWidget(bar)

        self.table = QTableWidget(0, 8)
        self.table.setHorizontalHeaderLabels([
            "Raised",
            "Flat",
            "Title",
            "Category",
            "Priority",
            "Status",
            "Assigned to",
            "Raised by",
        ])
        style_table(self.table, stretch_cols=[2, 6])
        self.table.doubleClicked.connect(self._on_edit)
        layout.addWidget(self.table, 1)

    def refresh(self):
        self.table.setSortingEnabled(False)
        status_filter = self.status_filter.currentData()
        rows = self.svc.list(status=status_filter)

        self.table.setRowCount(len(rows))
        for r, c in enumerate(rows):
            raised = (c.get("raised_at") or "").split(" ")[0]
            item0 = QTableWidgetItem(raised)
            item0.setData(Qt.ItemDataRole.UserRole, c["id"])
            self.table.setItem(r, 0, item0)
            self.table.setItem(r, 1, QTableWidgetItem(c.get("flat_no") or ""))
            self.table.setItem(r, 2, QTableWidgetItem(c.get("title") or ""))
            self.table.setItem(r, 3, QTableWidgetItem(
                (c.get("category") or "").title()
            ))

            pr_item = QTableWidgetItem((c.get("priority") or "").title())
            pr_item.setForeground(QColor(THEME[_PRIORITY_COLORS.get(
                c.get("priority") or "NORMAL", "text_primary"
            )]))
            self.table.setItem(r, 4, pr_item)

            st_text = (c.get("status") or "").replace("_", " ").title()
            st_item = QTableWidgetItem(st_text)
            st_item.setForeground(QColor(THEME[_STATUS_COLORS.get(
                c.get("status") or "OPEN", "text_primary"
            )]))
            self.table.setItem(r, 5, st_item)

            self.table.setItem(r, 6, QTableWidgetItem(c.get("assigned_to") or ""))
            self.table.setItem(r, 7, QTableWidgetItem(c.get("raised_by_name") or ""))

        self.table.setSortingEnabled(True)
        apply_text_filter(self.table, self.filter_edit.text())

        s = self.svc.stats()
        bits = [
            f"<b>{s['open']}</b> open",
            f"<b>{s['in_progress']}</b> in progress",
            f"<b>{s['resolved']}</b> resolved",
        ]
        if s["urgent_open"]:
            bits.insert(0, f"<span style='color:{THEME['danger']};'><b>"
                          f"{s['urgent_open']} URGENT</b></span>")
        self.counters.setText("  ·  ".join(bits))

    def _selected_id(self) -> int | None:
        row = self.table.currentRow()
        if row < 0: return None
        item = self.table.item(row, 0)
        return item.data(Qt.ItemDataRole.UserRole) if item else None

    def _on_add(self):
        dlg = _ComplaintDialog(self.svc, self.flats, self.owners, parent=self)
        dlg.saved.connect(self.refresh)
        dlg.exec()

    def _on_edit(self, *_):
        cid = self._selected_id()
        if not cid:
            QMessageBox.information(
                self, "No complaint selected", "Pick a row first, then click Edit."
            )
            return
        dlg = _ComplaintDialog(self.svc, self.flats, self.owners,
                                complaint_id=cid, parent=self)
        dlg.saved.connect(self.refresh)
        dlg.exec()

    def _on_delete(self):
        cid = self._selected_id()
        if not cid:
            return
        complaint = self.svc.get(cid)
        if QMessageBox.question(
            self, "Delete complaint",
            f"Delete '{complaint.get('title','')}'? This can't be undone.",
        ) != QMessageBox.StandardButton.Yes:
            return
        self.svc.delete(cid)
        self.refresh()
