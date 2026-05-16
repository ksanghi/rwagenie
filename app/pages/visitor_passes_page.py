"""
Visitor Pass page — gate-issued or pre-authorised entry passes.

Admin creates a pass with visitor name, target flat, expected arrival
window. A short alphanumeric `pass_code` is generated automatically —
the gatekeeper checks it on arrival. Entry / exit times can be stamped
from this page or (later) from a gatekeeper-app endpoint.
"""
from __future__ import annotations

from PySide6.QtCore    import Qt, Signal, QDateTime
from PySide6.QtGui     import QColor
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QLineEdit,
    QTableWidget, QTableWidgetItem, QDialog, QFormLayout, QComboBox,
    QMessageBox, QFrame, QDateTimeEdit,
)

from app.theme    import THEME
from app.services.visitors import VisitorPassesService, VALID_PURPOSES
from app.services import FlatsService
from app.pages._common import style_table, apply_text_filter


class _PassDialog(QDialog):
    saved = Signal()

    def __init__(self, service: VisitorPassesService, flats: FlatsService,
                 pid: int | None = None, parent=None):
        super().__init__(parent)
        self.svc   = service
        self.flats = flats
        self.pid   = pid
        self._existing = service.get(pid) if pid else None

        self.setWindowTitle("Edit Visitor Pass" if pid else "New Visitor Pass")
        self.setMinimumWidth(540)
        self.setModal(True)

        layout = QVBoxLayout(self); layout.setSpacing(10)
        layout.setContentsMargins(20, 20, 20, 20)

        hdr = QLabel("✎ Edit Pass" if self._existing else "+ New Visitor Pass")
        hdr.setStyleSheet(
            f"font-size:14px; font-weight:bold; color:{THEME['accent']};"
        )
        layout.addWidget(hdr)

        form = QFormLayout(); form.setSpacing(8)
        e = self._existing or {}

        self.flat = QComboBox(); self.flat.setFixedHeight(32)
        self.flat.addItem("(no flat — common area)", None)
        for f in self.flats.list_flats(active_only=True):
            self.flat.addItem(f["flat_no"], f["id"])
        if e.get("flat_id"):
            self._select_combo(self.flat, e["flat_id"])
        form.addRow(QLabel("Visiting flat"), self.flat)

        self.visitor_name = QLineEdit(e.get("visitor_name") or "")
        self.visitor_name.setFixedHeight(32)
        self.visitor_name.setPlaceholderText("Visitor's full name")
        form.addRow(QLabel("Visitor name *"), self.visitor_name)

        self.visitor_phone = QLineEdit(e.get("visitor_phone") or "")
        self.visitor_phone.setFixedHeight(32)
        self.visitor_phone.setPlaceholderText("e.g. 98XXX12345")
        form.addRow(QLabel("Phone"), self.visitor_phone)

        self.vehicle_no = QLineEdit(e.get("vehicle_no") or "")
        self.vehicle_no.setFixedHeight(32)
        self.vehicle_no.setPlaceholderText("e.g. DL-1C-XX-9876")
        form.addRow(QLabel("Vehicle no."), self.vehicle_no)

        self.purpose = QComboBox(); self.purpose.setFixedHeight(32)
        for p in VALID_PURPOSES:
            self.purpose.addItem(p.title(), p)
        self._select_combo(self.purpose, e.get("purpose") or "GUEST")
        form.addRow(QLabel("Purpose"), self.purpose)

        self.expected_at = QDateTimeEdit()
        self.expected_at.setDisplayFormat("dd-MMM-yyyy hh:mm AP")
        self.expected_at.setFixedHeight(32)
        self.expected_at.setCalendarPopup(True)
        if e.get("expected_at"):
            self.expected_at.setDateTime(
                QDateTime.fromString(e["expected_at"], Qt.DateFormat.ISODate)
                or QDateTime.currentDateTime()
            )
        else:
            self.expected_at.setDateTime(QDateTime.currentDateTime())
        form.addRow(QLabel("Expected at"), self.expected_at)

        self.valid_until = QDateTimeEdit()
        self.valid_until.setDisplayFormat("dd-MMM-yyyy hh:mm AP")
        self.valid_until.setFixedHeight(32)
        self.valid_until.setCalendarPopup(True)
        if e.get("valid_until"):
            self.valid_until.setDateTime(
                QDateTime.fromString(e["valid_until"], Qt.DateFormat.ISODate)
                or QDateTime.currentDateTime().addSecs(8 * 3600)
            )
        else:
            # Default validity: 8 hours from now
            self.valid_until.setDateTime(
                QDateTime.currentDateTime().addSecs(8 * 3600)
            )
        form.addRow(QLabel("Valid until"), self.valid_until)

        self.issued_by = QLineEdit(e.get("issued_by") or "")
        self.issued_by.setFixedHeight(32)
        self.issued_by.setPlaceholderText("Resident / gate / committee member")
        form.addRow(QLabel("Issued by"), self.issued_by)

        # Pass-code chip (read-only, generated server-side)
        if e.get("pass_code"):
            code = QLabel(f"<b style='font-size:18px; color:{THEME['accent']};'>"
                          f"{e['pass_code']}</b>")
            form.addRow(QLabel("Pass code"), code)

        layout.addLayout(form)

        # Entry / exit stamping (visible only when editing)
        if self._existing:
            stamp_row = QHBoxLayout(); stamp_row.setSpacing(6)
            if not e.get("entry_time"):
                in_btn = QPushButton("Mark entered now")
                in_btn.clicked.connect(self._mark_entered)
                stamp_row.addWidget(in_btn)
            else:
                stamp_row.addWidget(QLabel(f"Entered: {e['entry_time']}"))
            if e.get("entry_time") and not e.get("exit_time"):
                out_btn = QPushButton("Mark exited now")
                out_btn.clicked.connect(self._mark_exited)
                stamp_row.addWidget(out_btn)
            elif e.get("exit_time"):
                stamp_row.addWidget(QLabel(f"Exited: {e['exit_time']}"))
            stamp_row.addStretch()
            layout.addLayout(stamp_row)

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

    def _mark_entered(self):
        if not self.pid:
            return
        self.svc.mark_entered(self.pid)
        self.saved.emit()
        self.accept()

    def _mark_exited(self):
        if not self.pid:
            return
        self.svc.mark_exited(self.pid)
        self.saved.emit()
        self.accept()

    def _save(self):
        for w in (self.visitor_name, self.visitor_phone, self.vehicle_no,
                  self.issued_by):
            try: w.clearFocus()
            except Exception: pass

        kw = dict(
            flat_id=self.flat.currentData(),
            visitor_name=self.visitor_name.text().strip(),
            visitor_phone=self.visitor_phone.text().strip(),
            vehicle_no=self.vehicle_no.text().strip().upper(),
            purpose=self.purpose.currentData(),
            expected_at=self.expected_at.dateTime().toString(Qt.DateFormat.ISODate),
            valid_until=self.valid_until.dateTime().toString(Qt.DateFormat.ISODate),
            issued_by=self.issued_by.text().strip(),
        )
        try:
            if self.pid:
                self.svc.update(self.pid, **kw)
            else:
                created = self.svc.add(**kw)
                # Show the generated pass code to the issuer
                QMessageBox.information(
                    self, "Pass created",
                    f"Visitor pass for {created['visitor_name']}\n\n"
                    f"Pass code: {created['pass_code']}\n\n"
                    f"Give this code to the visitor. The gate will check it on arrival.",
                )
        except ValueError as e:
            QMessageBox.warning(self, "Cannot save", str(e))
            return
        self.saved.emit()
        self.accept()


class VisitorPassPage(QWidget):
    def __init__(self, db, company_id: int, tree, parent=None):
        super().__init__(parent)
        self.svc   = VisitorPassesService(db, company_id)
        self.flats = FlatsService(db, company_id, tree)
        self._build_ui()
        self.refresh()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 16, 24, 24); layout.setSpacing(10)

        title = QLabel("Visitor Pass")
        title.setObjectName("page_title")
        layout.addWidget(title)
        sub = QLabel(
            "Gate-issued or pre-authorised entry passes. Each pass gets a "
            "short alphanumeric code; the gatekeeper verifies on arrival "
            "and marks entry / exit times."
        )
        sub.setObjectName("page_subtitle")
        layout.addWidget(sub)

        bar = QFrame(); bar.setObjectName("card")
        bar_l = QHBoxLayout(bar)
        bar_l.setContentsMargins(10, 6, 10, 6); bar_l.setSpacing(8)

        self.filter_edit = QLineEdit()
        self.filter_edit.setPlaceholderText(
            "🔍 Filter by visitor / flat / vehicle / code…"
        )
        self.filter_edit.setFixedHeight(30)
        self.filter_edit.setClearButtonEnabled(True)
        self.filter_edit.textChanged.connect(
            lambda t: apply_text_filter(self.table, t)
        )
        bar_l.addWidget(self.filter_edit, 3)

        self.show_all = QPushButton("Show all history")
        self.show_all.setCheckable(True)
        self.show_all.setFixedHeight(30)
        self.show_all.toggled.connect(lambda _: self.refresh())
        bar_l.addWidget(self.show_all)

        add_btn = QPushButton("+ New Pass")
        add_btn.setObjectName("btn_primary"); add_btn.setFixedHeight(30)
        add_btn.clicked.connect(self._on_add)
        bar_l.addWidget(add_btn)

        edit_btn = QPushButton("Edit / Stamp"); edit_btn.setFixedHeight(30)
        edit_btn.clicked.connect(self._on_edit)
        bar_l.addWidget(edit_btn)

        del_btn = QPushButton("Delete"); del_btn.setFixedHeight(30)
        del_btn.clicked.connect(self._on_delete)
        bar_l.addWidget(del_btn)

        layout.addWidget(bar)

        self.table = QTableWidget(0, 9)
        self.table.setHorizontalHeaderLabels([
            "Code", "Visitor", "Flat", "Phone",
            "Vehicle", "Purpose",
            "Expected", "Entered", "Exited",
        ])
        style_table(self.table, stretch_cols=[1])
        self.table.doubleClicked.connect(self._on_edit)
        layout.addWidget(self.table, 1)

        self.summary = QLabel("")
        self.summary.setStyleSheet(
            f"color:{THEME['text_secondary']}; font-size:11px; padding:4px;"
        )
        layout.addWidget(self.summary)

    def refresh(self):
        self.table.setSortingEnabled(False)
        rows = self.svc.list(active_only=not self.show_all.isChecked())
        self.table.setRowCount(len(rows))
        for r, v in enumerate(rows):
            code_item = QTableWidgetItem(v.get("pass_code") or "")
            code_item.setData(Qt.ItemDataRole.UserRole, v["id"])
            # Bold + accent for the pass code so it stands out.
            font = code_item.font(); font.setBold(True)
            code_item.setFont(font)
            code_item.setForeground(QColor(THEME["accent"]))
            self.table.setItem(r, 0, code_item)
            self.table.setItem(r, 1, QTableWidgetItem(v.get("visitor_name") or ""))
            self.table.setItem(r, 2, QTableWidgetItem(v.get("flat_no") or ""))
            self.table.setItem(r, 3, QTableWidgetItem(v.get("visitor_phone") or ""))
            self.table.setItem(r, 4, QTableWidgetItem(v.get("vehicle_no") or ""))
            self.table.setItem(r, 5, QTableWidgetItem(
                (v.get("purpose") or "").title()
            ))
            self.table.setItem(r, 6, QTableWidgetItem(
                (v.get("expected_at") or "").replace("T", " ")
            ))
            self.table.setItem(r, 7, QTableWidgetItem(
                (v.get("entry_time") or "—").replace("T", " ")
            ))
            self.table.setItem(r, 8, QTableWidgetItem(
                (v.get("exit_time") or "—").replace("T", " ")
            ))
        self.table.setSortingEnabled(True)
        apply_text_filter(self.table, self.filter_edit.text())
        active = sum(1 for v in rows if not v.get("exit_time"))
        self.summary.setText(
            f"{len(rows)} pass(es)  ·  {active} not yet exited"
        )

    def _selected_id(self) -> int | None:
        row = self.table.currentRow()
        if row < 0: return None
        item = self.table.item(row, 0)
        return item.data(Qt.ItemDataRole.UserRole) if item else None

    def _on_add(self):
        dlg = _PassDialog(self.svc, self.flats, parent=self)
        dlg.saved.connect(self.refresh)
        dlg.exec()

    def _on_edit(self, *_):
        pid = self._selected_id()
        if not pid:
            QMessageBox.information(self, "No pass selected",
                                    "Pick a row first, then click Edit.")
            return
        dlg = _PassDialog(self.svc, self.flats, pid=pid, parent=self)
        dlg.saved.connect(self.refresh)
        dlg.exec()

    def _on_delete(self):
        pid = self._selected_id()
        if not pid:
            return
        p = self.svc.get(pid)
        if QMessageBox.question(
            self, "Delete pass",
            f"Delete pass {p.get('pass_code','')} for {p.get('visitor_name','')}?",
        ) != QMessageBox.StandardButton.Yes:
            return
        self.svc.delete(pid)
        self.refresh()
