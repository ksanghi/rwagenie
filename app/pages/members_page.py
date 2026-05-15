"""
Member Directory page — list of all people (owners, tenants, family)
linked to flats in this society. CRUD on rwa_owners plus flat-assignment
sub-dialog.

Ships with filter + sortable headers, per the tables-need-filter-and-sort
project convention.
"""
from __future__ import annotations

from PySide6.QtCore    import Qt, Signal, QDate
from PySide6.QtGui     import QColor
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QLineEdit,
    QTableWidget, QTableWidgetItem, QHeaderView, QAbstractItemView,
    QDialog, QFormLayout, QComboBox, QMessageBox, QFrame, QSizePolicy,
    QCheckBox, QTextEdit, QTabWidget, QDoubleSpinBox,
)

from ui.widgets import SmartDateEdit          # sibling import from AG
from app.theme  import THEME
from app.services import (
    OwnersService, FlatsService,
    VALID_PAYMENT_MODES, VALID_LINK_ROLES,
)


_KYC_TYPES = ["", "AADHAR", "PAN", "VOTER ID", "PASSPORT", "DL"]


class _OwnerDialog(QDialog):
    """Add/edit a person. Tabbed:
       Contact — name, phones, email, addresses
       KYC     — PAN, Aadhaar (last 4), photo
       Payment — UPI / bank / NACH
       Other   — emergency contact + notes
    """
    saved = Signal()

    def __init__(self, service: OwnersService, owner_id: int | None = None,
                 parent=None):
        super().__init__(parent)
        self.service = service
        self.owner_id = owner_id
        self._existing = self.service.get_owner(owner_id) if owner_id else None

        self.setWindowTitle("Edit Member" if owner_id else "Add Member")
        self.setMinimumWidth(580); self.setMinimumHeight(460)
        self.setModal(True)

        layout = QVBoxLayout(self); layout.setSpacing(10)
        layout.setContentsMargins(20, 20, 20, 20)

        hdr = QLabel("✎ Edit Member" if self._existing else "+ Add Member")
        hdr.setStyleSheet(
            f"font-size:14px; font-weight:bold; color:{THEME['accent']};"
        )
        layout.addWidget(hdr)

        tabs = QTabWidget()
        tabs.addTab(self._build_contact_tab(), "Contact")
        tabs.addTab(self._build_kyc_tab(),     "KYC")
        tabs.addTab(self._build_payment_tab(), "Payment")
        tabs.addTab(self._build_other_tab(),   "Other")
        layout.addWidget(tabs, 1)

        btn_row = QHBoxLayout(); btn_row.addStretch()
        cancel = QPushButton("Cancel"); cancel.clicked.connect(self.reject)
        save   = QPushButton("Save"); save.setObjectName("btn_primary")
        save.clicked.connect(self._save)
        btn_row.addWidget(cancel); btn_row.addWidget(save)
        layout.addLayout(btn_row)

    # ── Tabs ────────────────────────────────────────────────────────

    def _build_contact_tab(self) -> QWidget:
        w = QWidget(); form = QFormLayout(w); form.setSpacing(8)
        e = self._existing or {}

        self.name = QLineEdit(e.get("name") or "")
        self.name.setFixedHeight(32)
        self.name.setPlaceholderText("Full name")
        form.addRow(QLabel("Name *"), self.name)

        self.primary_phone = QLineEdit(e.get("primary_phone") or "")
        self.primary_phone.setFixedHeight(32)
        self.primary_phone.setPlaceholderText("e.g. 98XXX12345")
        form.addRow(QLabel("Primary phone"), self.primary_phone)

        self.alt_phone = QLineEdit(e.get("alternate_phone") or "")
        self.alt_phone.setFixedHeight(32)
        form.addRow(QLabel("Alternate phone"), self.alt_phone)

        self.email = QLineEdit(e.get("email") or "")
        self.email.setFixedHeight(32)
        form.addRow(QLabel("Email"), self.email)

        self.address = QTextEdit(e.get("correspondence_address") or "")
        self.address.setFixedHeight(60)
        self.address.setPlaceholderText(
            "Mailing address (only if different from the flat — "
            "absentee owners use this)"
        )
        form.addRow(QLabel("Correspondence address"), self.address)

        self.is_resident = QCheckBox(
            "Lives in their own flat (uncheck for absentee owners)"
        )
        self.is_resident.setChecked(bool(e.get("is_resident", 1)))
        form.addRow("", self.is_resident)

        return w

    def _build_kyc_tab(self) -> QWidget:
        w = QWidget(); form = QFormLayout(w); form.setSpacing(8)
        e = self._existing or {}

        self.pan = QLineEdit((e.get("pan") or "").upper())
        self.pan.setFixedHeight(32)
        self.pan.setPlaceholderText("e.g. ABCDE1234F")
        self.pan.setMaxLength(10)
        form.addRow(QLabel("PAN"), self.pan)

        self.aadhaar_last4 = QLineEdit(e.get("aadhaar_last4") or "")
        self.aadhaar_last4.setFixedHeight(32)
        self.aadhaar_last4.setMaxLength(4)
        self.aadhaar_last4.setPlaceholderText("XXXX (last 4 digits only)")
        form.addRow(QLabel("Aadhaar (last 4)"), self.aadhaar_last4)

        hint = QLabel(
            "Aadhaar — store only the last 4 digits per compliance "
            "convention. The full number lives on the physical KYC "
            "form filed by the society."
        )
        hint.setWordWrap(True)
        hint.setStyleSheet(f"color:{THEME['text_secondary']}; font-size:10px;")
        form.addRow("", hint)

        # Older "generic KYC" fields kept for back-compat
        self.kyc_type = QComboBox(); self.kyc_type.setFixedHeight(32)
        self.kyc_type.addItems(_KYC_TYPES)
        if e.get("kyc_id_type"):
            i = self.kyc_type.findText(e["kyc_id_type"])
            if i >= 0: self.kyc_type.setCurrentIndex(i)
        form.addRow(QLabel("Other ID type"), self.kyc_type)

        self.kyc_number = QLineEdit(e.get("kyc_id_number") or "")
        self.kyc_number.setFixedHeight(32)
        form.addRow(QLabel("Other ID number"), self.kyc_number)

        return w

    def _build_payment_tab(self) -> QWidget:
        w = QWidget(); form = QFormLayout(w); form.setSpacing(8)
        e = self._existing or {}

        self.mode = QComboBox(); self.mode.setFixedHeight(32)
        self.mode.addItem("(not set)", "")
        for m in VALID_PAYMENT_MODES:
            self.mode.addItem(m.title(), m)
        if e.get("preferred_payment_mode"):
            for i in range(self.mode.count()):
                if self.mode.itemData(i) == e["preferred_payment_mode"]:
                    self.mode.setCurrentIndex(i); break
        form.addRow(QLabel("Preferred mode"), self.mode)

        self.upi_id = QLineEdit(e.get("upi_id") or "")
        self.upi_id.setFixedHeight(32)
        self.upi_id.setPlaceholderText("e.g. krishan@oksbi, 98xxx@paytm")
        form.addRow(QLabel("UPI ID"), self.upi_id)

        self.bank_acc = QLineEdit(e.get("bank_account_no") or "")
        self.bank_acc.setFixedHeight(32)
        self.bank_acc.setPlaceholderText("Bank account number (for NACH / transfer)")
        form.addRow(QLabel("Bank A/c No."), self.bank_acc)

        self.ifsc = QLineEdit(e.get("bank_ifsc") or "")
        self.ifsc.setFixedHeight(32)
        self.ifsc.setMaxLength(11)
        self.ifsc.setPlaceholderText("e.g. HDFC0001234")
        form.addRow(QLabel("IFSC"), self.ifsc)

        self.acc_holder = QLineEdit(e.get("bank_account_holder_name") or "")
        self.acc_holder.setFixedHeight(32)
        self.acc_holder.setPlaceholderText(
            "Only if account is in a different name (joint, HUF)"
        )
        form.addRow(QLabel("A/c holder name"), self.acc_holder)

        self.nach_ref = QLineEdit(e.get("nach_mandate_ref") or "")
        self.nach_ref.setFixedHeight(32)
        self.nach_ref.setPlaceholderText(
            "UMRN — filled when the society registers an auto-debit"
        )
        form.addRow(QLabel("NACH mandate ref"), self.nach_ref)

        return w

    def _build_other_tab(self) -> QWidget:
        w = QWidget(); form = QFormLayout(w); form.setSpacing(8)
        e = self._existing or {}

        self.emergency_name = QLineEdit(e.get("emergency_name") or "")
        self.emergency_name.setFixedHeight(32)
        form.addRow(QLabel("Emergency contact"), self.emergency_name)

        self.emergency_phone = QLineEdit(e.get("emergency_phone") or "")
        self.emergency_phone.setFixedHeight(32)
        form.addRow(QLabel("Emergency phone"), self.emergency_phone)

        self.notes = QTextEdit(e.get("notes") or "")
        self.notes.setFixedHeight(100)
        form.addRow(QLabel("Notes"), self.notes)

        return w

    # ── Save ────────────────────────────────────────────────────────

    def _save(self):
        for w in (self.name, self.primary_phone, self.alt_phone, self.email,
                  self.pan, self.aadhaar_last4, self.kyc_number,
                  self.upi_id, self.bank_acc, self.ifsc, self.acc_holder,
                  self.nach_ref,
                  self.emergency_name, self.emergency_phone):
            try: w.clearFocus()
            except Exception: pass

        data = dict(
            name=self.name.text().strip(),
            primary_phone=self.primary_phone.text().strip(),
            alternate_phone=self.alt_phone.text().strip(),
            email=self.email.text().strip(),
            correspondence_address=self.address.toPlainText().strip(),
            is_resident=int(self.is_resident.isChecked()),
            pan=self.pan.text().strip().upper(),
            aadhaar_last4=self.aadhaar_last4.text().strip(),
            kyc_id_type=self.kyc_type.currentText().strip() or None,
            kyc_id_number=self.kyc_number.text().strip(),
            preferred_payment_mode=(self.mode.currentData() or "").strip() or None,
            upi_id=self.upi_id.text().strip(),
            bank_account_no=self.bank_acc.text().strip(),
            bank_ifsc=self.ifsc.text().strip().upper(),
            bank_account_holder_name=self.acc_holder.text().strip(),
            nach_mandate_ref=self.nach_ref.text().strip(),
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
    """Assign this member to a flat with a role, with tenancy details
    surfaced when role=TENANT (police verification ref + dates + rent
    + deposit + lease doc path)."""
    saved = Signal()

    def __init__(self, flats_service: FlatsService, owner_id: int,
                 owner_name: str, parent=None):
        super().__init__(parent)
        self.flats = flats_service
        self.owner_id = owner_id

        self.setWindowTitle(f"Assign {owner_name} to a flat")
        self.setMinimumWidth(480)
        self.setModal(True)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20); layout.setSpacing(10)

        form = QFormLayout(); form.setSpacing(8)

        flats = self.flats.list_flats(active_only=True)
        self.flat_combo = QComboBox(); self.flat_combo.setFixedHeight(32)
        for f in flats:
            self.flat_combo.addItem(f["flat_no"], f["id"])
        form.addRow(QLabel("Flat *"), self.flat_combo)

        self.role = QComboBox(); self.role.setFixedHeight(32)
        for r in VALID_LINK_ROLES:
            self.role.addItem(r.title(), r)
        self.role.currentIndexChanged.connect(self._on_role_change)
        form.addRow(QLabel("Role"), self.role)

        self.is_primary = QCheckBox(
            "Primary billing contact for this flat in this role"
        )
        form.addRow("", self.is_primary)

        # Tenancy-only widgets — shown only when role=TENANT
        self._tenancy_widgets: list[QWidget] = []

        self.tenancy_from = SmartDateEdit()
        self.tenancy_from.setDisplayFormat("dd-MMM-yyyy")
        self.tenancy_from.setFixedHeight(32)
        form.addRow(QLabel("Tenancy from"), self.tenancy_from)
        self._tenancy_widgets.append(self.tenancy_from)

        self.tenancy_to = SmartDateEdit()
        self.tenancy_to.setDisplayFormat("dd-MMM-yyyy")
        self.tenancy_to.setFixedHeight(32)
        form.addRow(QLabel("Tenancy to"), self.tenancy_to)
        self._tenancy_widgets.append(self.tenancy_to)

        self.police_ref = QLineEdit()
        self.police_ref.setFixedHeight(32)
        self.police_ref.setPlaceholderText("e.g. PS-Vasant-Kunj/2025/0421")
        form.addRow(QLabel("Police verif. ref"), self.police_ref)
        self._tenancy_widgets.append(self.police_ref)

        self.police_date = SmartDateEdit()
        self.police_date.setDisplayFormat("dd-MMM-yyyy")
        self.police_date.setFixedHeight(32)
        form.addRow(QLabel("Police verif. date"), self.police_date)
        self._tenancy_widgets.append(self.police_date)

        self.monthly_rent = QDoubleSpinBox()
        self.monthly_rent.setRange(0, 9999999); self.monthly_rent.setDecimals(0)
        self.monthly_rent.setPrefix("₹ "); self.monthly_rent.setFixedHeight(32)
        form.addRow(QLabel("Monthly rent"), self.monthly_rent)
        self._tenancy_widgets.append(self.monthly_rent)

        self.deposit = QDoubleSpinBox()
        self.deposit.setRange(0, 99999999); self.deposit.setDecimals(0)
        self.deposit.setPrefix("₹ "); self.deposit.setFixedHeight(32)
        form.addRow(QLabel("Security deposit"), self.deposit)
        self._tenancy_widgets.append(self.deposit)

        layout.addLayout(form)

        btn_row = QHBoxLayout(); btn_row.addStretch()
        cancel = QPushButton("Cancel"); cancel.clicked.connect(self.reject)
        save = QPushButton("Assign"); save.setObjectName("btn_primary")
        save.clicked.connect(self._save)
        btn_row.addWidget(cancel); btn_row.addWidget(save)
        layout.addLayout(btn_row)

        self._on_role_change()

    def _on_role_change(self, *_):
        role = self.role.currentData()
        is_tenant = role == "TENANT"
        # Show/hide tenancy rows. QFormLayout doesn't have row visibility
        # API directly; toggle the widgets and they take their labels.
        for w in self._tenancy_widgets:
            w.setVisible(is_tenant)
            # Also hide the label sibling — find via QFormLayout API
            lbl = None
            try:
                # QFormLayout::labelForField returns the buddy label.
                from PySide6.QtWidgets import QFormLayout as _F
                parent_form = self.findChild(_F)
                if parent_form is not None:
                    lbl = parent_form.labelForField(w)
            except Exception:
                pass
            if lbl is not None:
                lbl.setVisible(is_tenant)

    def _save(self):
        flat_id = self.flat_combo.currentData()
        role = self.role.currentData()
        if not flat_id:
            QMessageBox.warning(self, "Pick a flat", "Add a flat first.")
            return

        def _iso(date_edit) -> str | None:
            d = date_edit.date()
            if not d.isValid() or d.year() < 1990:
                return None
            return d.toString("yyyy-MM-dd")

        try:
            self.flats.assign_owner(
                flat_id=flat_id,
                owner_id=self.owner_id,
                role=role,
                is_primary=self.is_primary.isChecked(),
                tenancy_from=_iso(self.tenancy_from)        if role == "TENANT" else None,
                tenancy_to=_iso(self.tenancy_to)            if role == "TENANT" else None,
                police_verification_ref=(self.police_ref.text().strip() or None) if role == "TENANT" else None,
                police_verification_date=_iso(self.police_date) if role == "TENANT" else None,
                monthly_rent=(self.monthly_rent.value() or None) if role == "TENANT" else None,
                security_deposit=(self.deposit.value() or None)  if role == "TENANT" else None,
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
        self.owners = OwnersService(db, company_id)
        self.flats  = FlatsService(db, company_id, tree)
        self._build_ui()
        self.refresh()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 16, 24, 24); layout.setSpacing(10)

        title = QLabel("Member Directory")
        title.setObjectName("page_title")
        layout.addWidget(title)
        sub = QLabel(
            "People associated with the society — owners, tenants, "
            "family. Link a person to one or more flats."
        )
        sub.setObjectName("page_subtitle")
        layout.addWidget(sub)

        bar = QFrame(); bar.setObjectName("card")
        bar_l = QHBoxLayout(bar)
        bar_l.setContentsMargins(10, 6, 10, 6); bar_l.setSpacing(8)

        self.filter_edit = QLineEdit()
        self.filter_edit.setPlaceholderText(
            "🔍 Filter by name / phone / email / flat / UPI…"
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
        add_btn.setObjectName("btn_primary"); add_btn.setFixedHeight(30)
        add_btn.clicked.connect(self._on_add)
        bar_l.addWidget(add_btn)

        edit_btn = QPushButton("Edit"); edit_btn.setFixedHeight(30)
        edit_btn.clicked.connect(self._on_edit)
        bar_l.addWidget(edit_btn)

        assign_btn = QPushButton("Assign to flat…")
        assign_btn.setFixedHeight(30); assign_btn.clicked.connect(self._on_assign)
        bar_l.addWidget(assign_btn)

        layout.addWidget(bar)

        self.table = QTableWidget(0, 7)
        self.table.setHorizontalHeaderLabels([
            "Name", "Phone", "Email", "PAN", "Payment", "Flats", "Status",
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
        hdr.setSectionResizeMode(5, QHeaderView.ResizeMode.Stretch)
        self.table.doubleClicked.connect(self._on_edit)
        layout.addWidget(self.table, 1)

        self.summary = QLabel("")
        self.summary.setStyleSheet(
            f"color:{THEME['text_secondary']}; font-size:11px; padding:4px;"
        )
        layout.addWidget(self.summary)

    def refresh(self):
        self.table.setSortingEnabled(False)
        owners = self.owners.list_owners(
            active_only=not self.show_inactive.isChecked()
        )
        self.table.setRowCount(len(owners))
        for r, o in enumerate(owners):
            name_item = QTableWidgetItem(o.get("name") or "")
            name_item.setData(Qt.ItemDataRole.UserRole, o["id"])
            self.table.setItem(r, 0, name_item)
            self.table.setItem(r, 1, QTableWidgetItem(o.get("primary_phone") or ""))
            self.table.setItem(r, 2, QTableWidgetItem(o.get("email") or ""))
            self.table.setItem(r, 3, QTableWidgetItem(o.get("pan") or ""))

            # Payment summary — mode + the most-actionable detail
            mode = (o.get("preferred_payment_mode") or "").strip()
            pay_summary = ""
            if mode == "UPI" and o.get("upi_id"):
                pay_summary = f"UPI · {o['upi_id']}"
            elif mode == "NACH" and o.get("nach_mandate_ref"):
                pay_summary = f"NACH · {o['nach_mandate_ref'][:12]}"
            elif mode and (o.get("bank_account_no") or o.get("bank_ifsc")):
                acc = (o.get("bank_account_no") or "")[-4:]
                pay_summary = f"{mode.title()} · ····{acc}"
            elif mode:
                pay_summary = mode.title()
            self.table.setItem(r, 4, QTableWidgetItem(pay_summary or "—"))

            self.table.setItem(r, 5, QTableWidgetItem(o.get("flats_csv") or "—"))

            status_text = "Active" if o.get("active") else "Inactive"
            if o.get("is_resident") == 0:
                status_text = ("Absentee" if o.get("active") else "Absentee (inactive)")
            status_item = QTableWidgetItem(status_text)
            if not o.get("active"):
                status_item.setForeground(QColor(THEME["text_dim"]))
            self.table.setItem(r, 6, status_item)

        self.table.setSortingEnabled(True)
        self._apply_filter(self.filter_edit.text())
        self.summary.setText(
            f"{len(owners)} member(s)"
            + ("  ·  showing inactive too" if self.show_inactive.isChecked() else "")
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
                    hit = True; break
            self.table.setRowHidden(r, not hit)

    def _selected_owner(self) -> dict | None:
        row = self.table.currentRow()
        if row < 0: return None
        item = self.table.item(row, 0)
        if not item: return None
        return {"id": item.data(Qt.ItemDataRole.UserRole), "name": item.text()}

    def _on_add(self):
        dlg = _OwnerDialog(self.owners, parent=self)
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
        dlg = _OwnerDialog(self.owners, owner_id=sel["id"], parent=self)
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
            self.flats, owner_id=sel["id"], owner_name=sel["name"],
            parent=self,
        )
        dlg.saved.connect(self.refresh)
        dlg.exec()
