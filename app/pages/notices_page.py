"""
Notice Board page — society-wide announcements.

Admins create notices that residents see (now in the desktop UI; later
via the resident web app). Pinned notices float to the top. Expired
notices stay in the DB but are hidden from the default view.
"""
from __future__ import annotations

from PySide6.QtCore    import Qt, Signal, QDate
from PySide6.QtGui     import QColor
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QLineEdit,
    QTableWidget, QTableWidgetItem, QHeaderView, QDialog, QFormLayout,
    QCheckBox, QTextEdit, QMessageBox, QFrame,
)

from ui.widgets   import SmartDateEdit
from app.theme    import THEME
from app.services.notices import NoticesService
from app.pages._common    import style_table, apply_text_filter


class _NoticeDialog(QDialog):
    saved = Signal()

    def __init__(self, service: NoticesService, notice_id: int | None = None,
                 parent=None):
        super().__init__(parent)
        self.service = service
        self.notice_id = notice_id
        self._existing = service.get(notice_id) if notice_id else None

        self.setWindowTitle("Edit Notice" if notice_id else "New Notice")
        self.setMinimumWidth(520)
        self.setModal(True)

        layout = QVBoxLayout(self); layout.setSpacing(10)
        layout.setContentsMargins(20, 20, 20, 20)

        hdr = QLabel("✎ Edit Notice" if self._existing else "+ New Notice")
        hdr.setStyleSheet(
            f"font-size:14px; font-weight:bold; color:{THEME['accent']};"
        )
        layout.addWidget(hdr)

        form = QFormLayout(); form.setSpacing(8)
        e = self._existing or {}

        self.title = QLineEdit(e.get("title") or "")
        self.title.setFixedHeight(32)
        self.title.setPlaceholderText("Short, scannable headline")
        form.addRow(QLabel("Title *"), self.title)

        self.body = QTextEdit(e.get("body") or "")
        self.body.setFixedHeight(140)
        self.body.setPlaceholderText("Full message — multiple lines OK.")
        form.addRow(QLabel("Message"), self.body)

        self.posted_by = QLineEdit(e.get("posted_by") or "")
        self.posted_by.setFixedHeight(32)
        self.posted_by.setPlaceholderText("Society Office / Secretary / your name")
        form.addRow(QLabel("Posted by"), self.posted_by)

        self.pinned = QCheckBox("Pin to top — keeps the notice prominent")
        self.pinned.setChecked(bool(e.get("pinned")))
        form.addRow("", self.pinned)

        self.expires = SmartDateEdit()
        self.expires.setDisplayFormat("dd-MMM-yyyy")
        self.expires.setFixedHeight(32)
        if e.get("expires_on"):
            self.expires.setDate(QDate.fromString(e["expires_on"], "yyyy-MM-dd"))
        else:
            # No expiry by default — set to far-future so the user picks
            # a real date only when they care.
            self.expires.setDate(QDate(2099, 12, 31))
        form.addRow(QLabel("Auto-hide after"), self.expires)

        layout.addLayout(form)

        btn_row = QHBoxLayout(); btn_row.addStretch()
        cancel = QPushButton("Cancel"); cancel.clicked.connect(self.reject)
        save   = QPushButton("Save"); save.setObjectName("btn_primary")
        save.clicked.connect(self._save)
        btn_row.addWidget(cancel); btn_row.addWidget(save)
        layout.addLayout(btn_row)

    def _save(self):
        for w in (self.title, self.posted_by):
            try: w.clearFocus()
            except Exception: pass

        d = self.expires.date()
        # If user left it at the sentinel 2099-12-31, treat as "no expiry"
        expires_on: str | None = None
        if d.isValid() and d.year() < 2099:
            expires_on = d.toString("yyyy-MM-dd")

        kw = dict(
            title=self.title.text().strip(),
            body=self.body.toPlainText().strip(),
            posted_by=self.posted_by.text().strip(),
            pinned=self.pinned.isChecked(),
            expires_on=expires_on,
        )
        try:
            if self.notice_id:
                self.service.update(self.notice_id, **kw)
            else:
                self.service.add(**kw)
        except ValueError as e:
            QMessageBox.warning(self, "Cannot save", str(e))
            return
        self.saved.emit()
        self.accept()


class NoticeBoardPage(QWidget):
    """Master list of notices with filter + sortable headers."""

    def __init__(self, db, company_id: int, tree, parent=None):
        super().__init__(parent)
        self.service = NoticesService(db, company_id)
        self._build_ui()
        self.refresh()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 16, 24, 24); layout.setSpacing(10)

        title = QLabel("Notice Board")
        title.setObjectName("page_title")
        layout.addWidget(title)
        sub = QLabel(
            "Society-wide announcements. Pinned items float to the top; "
            "set an auto-hide date so old notices fade naturally."
        )
        sub.setObjectName("page_subtitle")
        layout.addWidget(sub)

        bar = QFrame(); bar.setObjectName("card")
        bar_l = QHBoxLayout(bar)
        bar_l.setContentsMargins(10, 6, 10, 6); bar_l.setSpacing(8)

        self.filter_edit = QLineEdit()
        self.filter_edit.setPlaceholderText("🔍 Filter by title / message…")
        self.filter_edit.setFixedHeight(30)
        self.filter_edit.setClearButtonEnabled(True)
        self.filter_edit.textChanged.connect(
            lambda t: apply_text_filter(self.table, t)
        )
        bar_l.addWidget(self.filter_edit, 3)

        self.include_expired = QPushButton("Show expired")
        self.include_expired.setCheckable(True)
        self.include_expired.setFixedHeight(30)
        self.include_expired.toggled.connect(lambda _: self.refresh())
        bar_l.addWidget(self.include_expired)

        add_btn = QPushButton("+ New Notice")
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

        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels([
            "Title", "Message", "Posted by", "Pinned", "Expires", "Created",
        ])
        style_table(self.table, stretch_cols=[0, 1])
        self.table.doubleClicked.connect(self._on_edit)
        layout.addWidget(self.table, 1)

        self.summary = QLabel("")
        self.summary.setStyleSheet(
            f"color:{THEME['text_secondary']}; font-size:11px; padding:4px;"
        )
        layout.addWidget(self.summary)

    def refresh(self):
        self.table.setSortingEnabled(False)
        rows = self.service.list(
            include_expired=self.include_expired.isChecked()
        )
        self.table.setRowCount(len(rows))
        for r, n in enumerate(rows):
            title_item = QTableWidgetItem(n.get("title") or "")
            title_item.setData(Qt.ItemDataRole.UserRole, n["id"])
            if n.get("pinned"):
                title_item.setForeground(QColor(THEME["accent"]))
            self.table.setItem(r, 0, title_item)
            # Truncate body for the table view; full content shows in the editor.
            body = (n.get("body") or "").strip().replace("\n", "  ")
            self.table.setItem(r, 1, QTableWidgetItem(
                body[:120] + ("…" if len(body) > 120 else "")
            ))
            self.table.setItem(r, 2, QTableWidgetItem(n.get("posted_by") or ""))
            self.table.setItem(r, 3, QTableWidgetItem("📌" if n.get("pinned") else ""))
            self.table.setItem(r, 4, QTableWidgetItem(n.get("expires_on") or ""))
            self.table.setItem(r, 5, QTableWidgetItem(
                (n.get("created_at") or "").split(" ")[0]
            ))
        self.table.setSortingEnabled(True)
        apply_text_filter(self.table, self.filter_edit.text())
        self.summary.setText(
            f"{len(rows)} notice(s)"
            + ("  ·  including expired" if self.include_expired.isChecked() else "")
        )

    def _selected_id(self) -> int | None:
        row = self.table.currentRow()
        if row < 0: return None
        item = self.table.item(row, 0)
        return item.data(Qt.ItemDataRole.UserRole) if item else None

    def _on_add(self):
        dlg = _NoticeDialog(self.service, parent=self)
        dlg.saved.connect(self.refresh)
        dlg.exec()

    def _on_edit(self, *_):
        nid = self._selected_id()
        if not nid:
            QMessageBox.information(
                self, "No notice selected",
                "Pick a row first, then click Edit.",
            )
            return
        dlg = _NoticeDialog(self.service, notice_id=nid, parent=self)
        dlg.saved.connect(self.refresh)
        dlg.exec()

    def _on_delete(self):
        nid = self._selected_id()
        if not nid:
            return
        notice = self.service.get(nid)
        if not notice:
            return
        if QMessageBox.question(
            self, "Delete notice",
            f"Delete the notice '{notice.get('title','')}'? "
            "This can't be undone.",
        ) != QMessageBox.StandardButton.Yes:
            return
        self.service.delete(nid)
        self.refresh()
