"""
Polls page — society votes.

Admin composes a poll with 2+ options, opens it, residents vote (via
admin entry in v0.1 — resident web app comes later). The tally is
shown in the edit dialog with simple bar visualisation.
"""
from __future__ import annotations

from PySide6.QtCore    import Qt, Signal, QDate
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QLineEdit,
    QTableWidget, QTableWidgetItem, QDialog, QFormLayout, QComboBox,
    QTextEdit, QMessageBox, QFrame, QListWidget, QListWidgetItem,
    QInputDialog, QProgressBar,
)

from ui.widgets   import SmartDateEdit
from app.theme    import THEME
from app.services.polls import PollsService, VALID_STATUS, VALID_VOTE_PER
from app.pages._common import style_table, apply_text_filter


_STATUS_COLORS = {
    "DRAFT":    "text_secondary",
    "OPEN":     "success",
    "CLOSED":   "warning",
    "ARCHIVED": "text_dim",
}


class _PollDialog(QDialog):
    saved = Signal()

    def __init__(self, service: PollsService, pid: int | None = None,
                 parent=None):
        super().__init__(parent)
        self.svc = service
        self.pid = pid
        self._existing = service.get(pid) if pid else None

        self.setWindowTitle("Edit Poll" if pid else "New Poll")
        self.setMinimumWidth(560)
        self.setMinimumHeight(520)
        self.setModal(True)

        layout = QVBoxLayout(self); layout.setSpacing(10)
        layout.setContentsMargins(20, 20, 20, 20)

        hdr = QLabel("✎ Edit Poll" if self._existing else "+ New Poll")
        hdr.setStyleSheet(
            f"font-size:14px; font-weight:bold; color:{THEME['accent']};"
        )
        layout.addWidget(hdr)

        form = QFormLayout(); form.setSpacing(8)
        e = self._existing or {}

        self.title = QLineEdit(e.get("title") or "")
        self.title.setFixedHeight(32)
        self.title.setPlaceholderText("e.g. Pick the colour for the new gate")
        form.addRow(QLabel("Title *"), self.title)

        self.description = QTextEdit(e.get("description") or "")
        self.description.setFixedHeight(60)
        self.description.setPlaceholderText(
            "Optional context — what residents need to know before voting."
        )
        form.addRow(QLabel("Description"), self.description)

        # Options list with add/remove buttons
        options_widget = QWidget()
        ow = QVBoxLayout(options_widget); ow.setContentsMargins(0, 0, 0, 0)
        self.options = QListWidget()
        self.options.setFixedHeight(120)
        for o in e.get("options") or []:
            self.options.addItem(QListWidgetItem(str(o)))
        ow.addWidget(self.options)
        opt_row = QHBoxLayout(); opt_row.setSpacing(6)
        add_opt = QPushButton("+ Add option"); add_opt.setFixedHeight(28)
        add_opt.clicked.connect(self._add_option)
        del_opt = QPushButton("Remove"); del_opt.setFixedHeight(28)
        del_opt.clicked.connect(self._remove_option)
        opt_row.addWidget(add_opt); opt_row.addWidget(del_opt); opt_row.addStretch()
        ow.addLayout(opt_row)
        form.addRow(QLabel("Options *"), options_widget)

        self.one_vote_per = QComboBox(); self.one_vote_per.setFixedHeight(32)
        for v in VALID_VOTE_PER:
            self.one_vote_per.addItem(v.title(), v)
        self._select_combo(self.one_vote_per, e.get("one_vote_per") or "FLAT")
        form.addRow(QLabel("One vote per"), self.one_vote_per)

        self.opens_at = SmartDateEdit()
        self.opens_at.setDisplayFormat("dd-MMM-yyyy")
        self.opens_at.setFixedHeight(32)
        if e.get("opens_at"):
            self.opens_at.setDate(QDate.fromString(e["opens_at"][:10], "yyyy-MM-dd"))
        form.addRow(QLabel("Opens at"), self.opens_at)

        self.closes_at = SmartDateEdit()
        self.closes_at.setDisplayFormat("dd-MMM-yyyy")
        self.closes_at.setFixedHeight(32)
        if e.get("closes_at"):
            self.closes_at.setDate(QDate.fromString(e["closes_at"][:10], "yyyy-MM-dd"))
        form.addRow(QLabel("Closes at"), self.closes_at)

        self.status = QComboBox(); self.status.setFixedHeight(32)
        for s in VALID_STATUS:
            self.status.addItem(s.title(), s)
        self._select_combo(self.status, e.get("status") or "DRAFT")
        form.addRow(QLabel("Status"), self.status)

        layout.addLayout(form)

        # If editing an existing poll, show the current tally inline
        if self._existing and self._existing.get("tally"):
            tally_frame = QFrame(); tally_frame.setObjectName("card")
            tl = QVBoxLayout(tally_frame)
            tl.setContentsMargins(12, 10, 12, 10); tl.setSpacing(4)
            tl.addWidget(QLabel(f"<b>Tally — {sum(self._existing['tally'])} vote(s)</b>"))
            options_text = self._existing.get("options") or []
            tally = self._existing.get("tally") or []
            total = max(sum(tally), 1)
            for i, opt in enumerate(options_text):
                count = tally[i] if i < len(tally) else 0
                row = QHBoxLayout()
                lbl = QLabel(f"{opt}")
                lbl.setMinimumWidth(140)
                bar = QProgressBar()
                bar.setRange(0, total)
                bar.setValue(count)
                bar.setTextVisible(False)
                bar.setFixedHeight(14)
                cnt_lbl = QLabel(f"  {count}  ({count*100//total}%)")
                cnt_lbl.setStyleSheet(f"color:{THEME['text_secondary']}; font-size:11px;")
                cnt_lbl.setMinimumWidth(80)
                row.addWidget(lbl); row.addWidget(bar, 1); row.addWidget(cnt_lbl)
                tl.addLayout(row)
            layout.addWidget(tally_frame)

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

    def _add_option(self):
        text, ok = QInputDialog.getText(self, "New option", "Option text:")
        if ok and text.strip():
            self.options.addItem(QListWidgetItem(text.strip()))

    def _remove_option(self):
        idx = self.options.currentRow()
        if idx >= 0:
            self.options.takeItem(idx)

    def _options_list(self) -> list[str]:
        return [self.options.item(i).text() for i in range(self.options.count())]

    def _save(self):
        for w in (self.title,):
            try: w.clearFocus()
            except Exception: pass

        def _iso(d: SmartDateEdit) -> str | None:
            v = d.date()
            if not v.isValid() or v.year() < 1990:
                return None
            return v.toString("yyyy-MM-dd")

        kw = dict(
            title=self.title.text().strip(),
            description=self.description.toPlainText().strip(),
            opens_at=_iso(self.opens_at),
            closes_at=_iso(self.closes_at),
            one_vote_per=self.one_vote_per.currentData(),
            status=self.status.currentData(),
        )
        try:
            if self.pid:
                self.svc.update(self.pid, options=self._options_list(), **kw)
            else:
                self.svc.add(options=self._options_list(), **kw)
        except ValueError as e:
            QMessageBox.warning(self, "Cannot save", str(e))
            return
        self.saved.emit()
        self.accept()


class PollsPage(QWidget):
    def __init__(self, db, company_id: int, tree, parent=None):
        super().__init__(parent)
        self.svc = PollsService(db, company_id)
        self._build_ui()
        self.refresh()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 16, 24, 24); layout.setSpacing(10)

        title = QLabel("Polls")
        title.setObjectName("page_title")
        layout.addWidget(title)
        sub = QLabel(
            "AGM resolutions, amenity decisions. One vote per flat or per "
            "owner, configurable per poll. Tally shows live in the edit "
            "dialog."
        )
        sub.setObjectName("page_subtitle")
        layout.addWidget(sub)

        bar = QFrame(); bar.setObjectName("card")
        bar_l = QHBoxLayout(bar)
        bar_l.setContentsMargins(10, 6, 10, 6); bar_l.setSpacing(8)

        self.filter_edit = QLineEdit()
        self.filter_edit.setPlaceholderText("🔍 Filter by title…")
        self.filter_edit.setFixedHeight(30)
        self.filter_edit.setClearButtonEnabled(True)
        self.filter_edit.textChanged.connect(
            lambda t: apply_text_filter(self.table, t)
        )
        bar_l.addWidget(self.filter_edit, 3)

        self.status_filter = QComboBox(); self.status_filter.setFixedHeight(30)
        self.status_filter.addItem("All statuses", None)
        for s in VALID_STATUS:
            self.status_filter.addItem(s.title(), s)
        self.status_filter.currentIndexChanged.connect(lambda _: self.refresh())
        bar_l.addWidget(self.status_filter)

        add_btn = QPushButton("+ New Poll")
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
            "Title", "Status", "Votes", "Opens", "Closes", "Created",
        ])
        style_table(self.table, stretch_cols=[0])
        self.table.doubleClicked.connect(self._on_edit)
        layout.addWidget(self.table, 1)

    def refresh(self):
        from PySide6.QtGui import QColor
        self.table.setSortingEnabled(False)
        rows = self.svc.list(status=self.status_filter.currentData())
        self.table.setRowCount(len(rows))
        for r, p in enumerate(rows):
            t_item = QTableWidgetItem(p.get("title") or "")
            t_item.setData(Qt.ItemDataRole.UserRole, p["id"])
            self.table.setItem(r, 0, t_item)
            s_item = QTableWidgetItem((p.get("status") or "DRAFT").title())
            s_item.setForeground(QColor(THEME[_STATUS_COLORS.get(
                p.get("status") or "DRAFT", "text_primary"
            )]))
            self.table.setItem(r, 1, s_item)
            self.table.setItem(r, 2, QTableWidgetItem(str(p.get("vote_count") or 0)))
            self.table.setItem(r, 3, QTableWidgetItem(p.get("opens_at") or ""))
            self.table.setItem(r, 4, QTableWidgetItem(p.get("closes_at") or ""))
            self.table.setItem(r, 5, QTableWidgetItem(
                (p.get("created_at") or "").split(" ")[0]
            ))
        self.table.setSortingEnabled(True)
        apply_text_filter(self.table, self.filter_edit.text())

    def _selected_id(self) -> int | None:
        row = self.table.currentRow()
        if row < 0: return None
        item = self.table.item(row, 0)
        return item.data(Qt.ItemDataRole.UserRole) if item else None

    def _on_add(self):
        dlg = _PollDialog(self.svc, parent=self)
        dlg.saved.connect(self.refresh)
        dlg.exec()

    def _on_edit(self, *_):
        pid = self._selected_id()
        if not pid:
            QMessageBox.information(self, "No poll selected",
                                    "Pick a row first, then click Edit.")
            return
        dlg = _PollDialog(self.svc, pid=pid, parent=self)
        dlg.saved.connect(self.refresh)
        dlg.exec()

    def _on_delete(self):
        pid = self._selected_id()
        if not pid:
            return
        p = self.svc.get(pid)
        if QMessageBox.question(
            self, "Delete poll",
            f"Delete '{p.get('title','')}'? All recorded votes are deleted too.",
        ) != QMessageBox.StandardButton.Yes:
            return
        self.svc.delete(pid)
        self.refresh()
