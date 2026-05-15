"""
Member Directory page — list of all people (owners, tenants, family)
linked to flats in this society. CRUD on rwa_owners plus flat-assignment
sub-dialog.

Ships with filter + sortable headers, per the tables-need-filter-and-sort
project convention.
"""
from __future__ import annotations

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QLineEdit,
    QTableWidget, QTableWidgetItem, QHeaderView, QAbstractItemView,
    QDialog, QFormLayout, QComboBox, QMessageBox, QFrame, QSizePolicy,
    QCheckBox, QTextEdit,
)
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui  import QColor

from app.theme import THEME            # RWAGenie theme (mirrors AG for v0.1)
from app.services import OwnersService, FlatsService


_KYC_TYPES  = ["", "AADHAR", "PAN", "VOTER ID", "PASSPORT", "DL"]
_LINK_ROLES = ["OWNER", "TENANT", "FAMILY"]


class _OwnerDialog(QDialog):
    saved = Signal()

    def __init__(self, service: OwnersService, owner_id: int | None = None,
                 parent=None):
        super().__init__(parent)
        self.service = service
        self.owner_id = owner_id
        existing = self.service.get_owner(owner_id) if owner_id else None

        self.setWindowTitle("Edit Member" if existing else "Add Member")
        self.setMinimumWidth(500)
        self.setModal(True)

        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        layout.setContentsMargins(20, 20, 20, 20)

        hdr = QLabel("✎ Edit Member" if existing else "+ Add Member")
        hdr.setStyleSheet(
            f"font-size:14px; font-weight:bold; color:{THEME['accent']};"
        )
        layout.addWidget(hdr)

        form = QFormLayout()
        form.setSpacing(10)

        self.name = QLineEdit((existing or {}).get("name") or "")
        self.name.setPlaceholderText("Full name")
        self.name.setFixedHeight(34)
        form.addRow(QLabel("Name *"), self.name)

        self.primary_phone = QLineEdit((existing or {}).get("primary_phone") or "")
        self.primary_phone.setPlaceholderText("e.g. 98XXX12345")
        self.primary_phone.setFixedHeight(34)
        form.addRow(QLabel("Primary phone"), self.primary_phone)

        self.alt_phone = QLineEdit((existing or {}).get("alternate_phone") or "")
        self.alt_phone.setFixedHeight(34)
        form.addRow(QLabel("Alternate phone"), self.alt_phone)

        self.email = QLineEdit((existing or {}).get("email") or "")
        self.email.setFixedHeight(34)
        form.addRow(QLabel("Email"), self.email)

        kyc_row = QHBoxLayout()
        kyc_row.setSpacing(6)
        self.kyc_type = QComboBox()
        self.kyc_type.addItems(_KYC_TYPES)
        self.kyc_type.setFixedHeight(34)
        self.kyc_type.setFixedWidth(120)
        if existing and existing.get("kyc_id_type"):
            ix = self.kyc_type.findText(existing["kyc_id_type"])
            if ix >= 0:
                self.kyc_type.setCurrentIndex(ix)
        self.kyc_number = QLineEdit((existing or {}).get("kyc_id_number") or "")
        self.kyc_number.setPlaceholderText("ID number")
        self.kyc_number.setFixedHeight(34)
        kyc_row.addWidget(self.kyc_type)
        kyc_row.addWidget(self.kyc_number, 1)
        form.addRow(QLabel("KYC"), kyc_row)

        self.emergency_name = QLineEdit((existing or {}).get("emergency_name") or "")
        self.emergency_name.setFixedHeight(34)
        form.addRow(QLabel("Emergency contact"), self.emergency_name)

        self.emergency_phone = QLineEdit((existing or {}).get("emergency_phone") or "")
        self.emergency_phone.setFixedHeight(34)
        form.addRow(QLabel("Emergency phone"), self.emergency_phone)

        self.notes = QTextEdit((existing or {}).get("notes") or "")
        self.notes.setFixedHeight(60)
        form.addRow(QLabel("Notes"), self.notes)

        layout.addLayout(form)

        btn_row = QHBoxLayout()
        btn_row.addStretch()
        cancel = QPushButton("Cancel")
        cancel.clicked.connect(self.reject)
        save = QPushButton("Save")
        save.setObjectName("btn_primary")
        save.clicked.connect(self._save)
        btn_row.addWidget(cancel)
        btn_row.addWidget(save)
        layout.addLayout(btn_row)

    def _save(self):
        for w in (self.name, self.primary_phone, self.alt_phone,
                  self.email, self.kyc_number, self.emergency_name,
                  self.emergency_phone):
            try:
                w.clearFocus()
            except Exception:
                pass
        data = dict(
            name=self.name.text().strip(),
            primary_phone=self.primary_phone.text().strip(),
            alternate_phone=self.alt_phone.text().strip(),
            email=self.email.text().strip(),
            kyc_id_type=self.kyc_type.currentText().strip() or None,
            kyc_id_number=self.kyc_number.text().strip(),
            emergency_name=self.emergency_name.text().strip(),
            emergency_phone=self.emergency_phone.text().strip(),
            notes=self.notes.toPlainText().strip(),
        )
        try:
            if self.owner_id:
                self.service.update_owner(self.owner_id, **data)
            else:
                self.service.add_owner(**data)
        except ValueError as e:
            QMessageBox.warning(self, "Cannot save", str(e))
            return
        except Exception as e:
            QMessageBox.critical(self, "Error", str(e))
            return
        self.saved.emit()
        self.accept()


class _AssignFlatDialog(QDialog):
    """Assign the current member to a flat with a role (owner / tenant /
    family) and primary-billing flag."""
    saved = Signal()

    def __init__(self, flats_service: FlatsService, owner_id: int,
                 owner_name: str, parent=None):
        super().__init__(parent)
        self.flats_service = flats_service
        self.owner_id = owner_id

        self.setWindowTitle(f"Assign {owner_name} to a flat")
        self.setMinimumWidth(420)
        self.setModal(True)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(12)

        form = QFormLayout()
        form.setSpacing(10)

        flats = self.flats_service.list_flats(active_only=True)
        self.flat_combo = QComboBox()
        self.flat_combo.setFixedHeight(34)
        for f in flats:
            self.flat_combo.addItem(f"{f['flat_no']}", f["id"])
        form.addRow(QLabel("Flat *"), self.flat_combo)

        self.role = QComboBox()
        self.role.addItems(_LINK_ROLES)
        self.role.setFixedHeight(34)
        form.addRow(QLabel("Role"), self.role)

        self.is_primary = QCheckBox(
            "Primary billing contact for this flat"
        )
        form.addRow("", self.is_primary)

        layout.addLayout(form)

        btn_row = QHBoxLayout()
        btn_row.addStretch()
        cancel = QPushButton("Cancel")
        cancel.clicked.connect(self.reject)
        save = QPushButton("Assign")
        save.setObjectName("btn_primary")
        save.clicked.connect(self._save)
        btn_row.addWidget(cancel)
        btn_row.addWidget(save)
        layout.addLayout(btn_row)

    def _save(self):
        flat_id = self.flat_combo.currentData()
        if not flat_id:
            QMessageBox.warning(self, "Pick a flat",
                                "There are no flats to assign to. Add a flat first.")
            return
        try:
            self.flats_service.assign_owner(
                flat_id=flat_id,
                owner_id=self.owner_id,
                role=self.role.currentText(),
                is_primary=self.is_primary.isChecked(),
            )
        except ValueError as e:
            QMessageBox.warning(self, "Cannot assign", str(e))
            return
        except Exception as e:
            QMessageBox.critical(self, "Error", str(e))
            return
        self.saved.emit()
        self.accept()


class MembersPage(QWidget):
    """Member directory — every person linked to a flat."""

    def __init__(self, db, company_id: int, tree, parent=None):
        super().__init__(parent)
        self.owners_service = OwnersService(db, company_id)
        self.flats_service  = FlatsService(db, company_id, tree)
        self._build_ui()
        self.refresh()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 16, 24, 24)
        layout.setSpacing(10)

        title = QLabel("Member Directory")
        title.setObjectName("page_title")
        layout.addWidget(title)
        sub = QLabel(
            "People associated with the society — owners, tenants, "
            "family. Link a member to one or more flats."
        )
        sub.setObjectName("page_subtitle")
        layout.addWidget(sub)

        bar = QFrame()
        bar.setObjectName("card")
        bar_l = QHBoxLayout(bar)
        bar_l.setContentsMargins(10, 6, 10, 6)
        bar_l.setSpacing(8)

        self.filter_edit = QLineEdit()
        self.filter_edit.setPlaceholderText(
            "🔍 Filter by name / phone / email / flat…"
        )
        self.filter_edit.setFixedHeight(30)
        self.filter_edit.setClearButtonEnabled(True)
        self.filter_edit.textChanged.connect(self._apply_filter)
        bar_l.addWidget(self.filter_edit, 3)

        self.show_inactive = QPushButton("Show inactive")
        self.show_inactive.setCheckable(True)
        self.show_inactive.setFixedHeight(30)
        self.show_inactive.toggled.connect(lambda _: self.refresh())
        bar_l.addWidget(self.show_inactive)

        add_btn = QPushButton("+ Add Member")
        add_btn.setObjectName("btn_primary")
        add_btn.setFixedHeight(30)
        add_btn.clicked.connect(self._on_add)
        bar_l.addWidget(add_btn)

        edit_btn = QPushButton("Edit")
        edit_btn.setFixedHeight(30)
        edit_btn.clicked.connect(self._on_edit)
        bar_l.addWidget(edit_btn)

        assign_btn = QPushButton("Assign to flat…")
        assign_btn.setFixedHeight(30)
        assign_btn.clicked.connect(self._on_assign)
        bar_l.addWidget(assign_btn)

        layout.addWidget(bar)

        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels([
            "Name", "Primary Phone", "Email", "KYC", "Flats", "Status",
        ])
        self.table.verticalHeader().setVisible(False)
        self.table.setAlternatingRowColors(True)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSortingEnabled(True)
        self.table.verticalHeader().setDefaultSectionSize(30)
        self.table.setStyleSheet(
            "QTableWidget::item { padding: 2px 8px; }"
            "QHeaderView::section { padding: 4px 8px; }"
        )
        hdr = self.table.horizontalHeader()
        hdr.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        hdr.setSectionResizeMode(4, QHeaderView.ResizeMode.Stretch)
        self.table.doubleClicked.connect(self._on_edit)
        layout.addWidget(self.table, 1)

        self.summary = QLabel("")
        self.summary.setStyleSheet(
            f"color:{THEME['text_secondary']}; font-size:11px; padding:4px;"
        )
        layout.addWidget(self.summary)

    def refresh(self):
        self.table.setSortingEnabled(False)
        owners = self.owners_service.list_owners(
            active_only=not self.show_inactive.isChecked()
        )
        self.table.setRowCount(len(owners))
        for r, o in enumerate(owners):
            name_item = QTableWidgetItem(o.get("name") or "")
            name_item.setData(Qt.ItemDataRole.UserRole, o["id"])
            self.table.setItem(r, 0, name_item)
            self.table.setItem(r, 1, QTableWidgetItem(o.get("primary_phone") or ""))
            self.table.setItem(r, 2, QTableWidgetItem(o.get("email") or ""))
            kyc = ""
            if o.get("kyc_id_type"):
                kyc = f"{o['kyc_id_type']} {(o.get('kyc_id_number') or '')[:6]}…"
            self.table.setItem(r, 3, QTableWidgetItem(kyc))
            self.table.setItem(r, 4, QTableWidgetItem(o.get("flats_csv") or "—"))
            status_item = QTableWidgetItem(
                "Active" if o.get("active") else "Inactive"
            )
            if not o.get("active"):
                status_item.setForeground(QColor(THEME["text_dim"]))
            self.table.setItem(r, 5, status_item)
        self.table.setSortingEnabled(True)
        self._apply_filter(self.filter_edit.text())
        self.summary.setText(
            f"{len(owners)} member(s)"
            + ("  ·  showing inactive too"
               if self.show_inactive.isChecked() else "")
        )

    def _apply_filter(self, text: str):
        needle = (text or "").strip().lower()
        for r in range(self.table.rowCount()):
            if not needle:
                self.table.setRowHidden(r, False)
                continue
            hit = False
            for c in range(self.table.columnCount()):
                item = self.table.item(r, c)
                if item and needle in (item.text() or "").lower():
                    hit = True
                    break
            self.table.setRowHidden(r, not hit)

    def _selected_owner(self) -> dict | None:
        row = self.table.currentRow()
        if row < 0:
            return None
        item = self.table.item(row, 0)
        if not item:
            return None
        return {"id": item.data(Qt.ItemDataRole.UserRole),
                "name": item.text()}

    def _on_add(self):
        dlg = _OwnerDialog(self.owners_service, parent=self)
        dlg.saved.connect(self.refresh)
        dlg.exec()

    def _on_edit(self, *_):
        sel = self._selected_owner()
        if not sel:
            QMessageBox.information(
                self, "No member selected",
                "Pick a row first, then click Edit.",
            )
            return
        dlg = _OwnerDialog(self.owners_service, owner_id=sel["id"], parent=self)
        dlg.saved.connect(self.refresh)
        dlg.exec()

    def _on_assign(self):
        sel = self._selected_owner()
        if not sel:
            QMessageBox.information(
                self, "No member selected",
                "Pick a member first, then Assign to flat…",
            )
            return
        dlg = _AssignFlatDialog(
            self.flats_service, owner_id=sel["id"], owner_name=sel["name"],
            parent=self,
        )
        dlg.saved.connect(self.refresh)
        dlg.exec()
