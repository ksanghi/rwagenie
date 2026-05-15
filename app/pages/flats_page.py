"""
Flats page — RWA's master list of flats / units. Each flat has a
companion Sundry Debtor ledger created automatically so maintenance
billing can post against it.

The table ships with a filter input and click-to-sort headers — per
the project-wide convention for any list whose row count can exceed
~10 entries.
"""
from __future__ import annotations

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QLineEdit,
    QTableWidget, QTableWidgetItem, QHeaderView, QAbstractItemView,
    QDialog, QFormLayout, QComboBox, QDoubleSpinBox, QSpinBox,
    QMessageBox, QSizePolicy, QFrame, QTabWidget,
)
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui  import QColor

from app.theme import THEME            # RWAGenie theme (mirrors AG for v0.1)
from ui.widgets import SmartDateEdit   # generic widget, sibling-imported from AG
from app.services import (
    FlatsService, OwnersService,
    VALID_OCCUPATION, VALID_BILL_PAYER,
)


_FLAT_TYPES = ["", "Studio", "1BHK", "1RK", "2BHK", "3BHK", "4BHK",
               "Penthouse", "Duplex", "Shop"]


def _opt_int(s: str) -> int | None:
    try:
        return int((s or "").strip())
    except (ValueError, TypeError):
        return None


def _opt_float(s) -> float | None:
    try:
        v = float(s)
        return v if v else None
    except (ValueError, TypeError):
        return None


class _FlatDialog(QDialog):
    """Add / edit a flat. Tabbed for density:
        Basic       — number, block, type, areas
        People      — primary owner, primary tenant, occupation, bill payer
        Property    — sale deed / possession / storage / parking
    """
    saved = Signal()

    def __init__(self,
                 flats_service: FlatsService,
                 owners_service: OwnersService,
                 flat_id: int | None = None,
                 parent=None):
        super().__init__(parent)
        self.flats = flats_service
        self.owners = owners_service
        self.flat_id = flat_id
        self.setWindowTitle("Edit Flat" if flat_id else "Add Flat")
        self.setMinimumWidth(560)
        self.setMinimumHeight(420)
        self.setModal(True)

        self._existing = self.flats.get_flat(flat_id) if flat_id else None

        layout = QVBoxLayout(self)
        layout.setSpacing(10)
        layout.setContentsMargins(20, 20, 20, 20)

        hdr = QLabel("✎ Edit Flat" if self._existing else "+ Add Flat")
        hdr.setStyleSheet(
            f"font-size:14px; font-weight:bold; color:{THEME['accent']};"
        )
        layout.addWidget(hdr)

        # ── Tabs ─────────────────────────────────────────────────────
        tabs = QTabWidget()
        tabs.addTab(self._build_basic_tab(),    "Basic")
        tabs.addTab(self._build_people_tab(),   "Owner / Tenant")
        tabs.addTab(self._build_property_tab(), "Property")
        layout.addWidget(tabs, 1)

        # ── Buttons ──────────────────────────────────────────────────
        btn_row = QHBoxLayout()
        btn_row.addStretch()
        cancel = QPushButton("Cancel"); cancel.clicked.connect(self.reject)
        save   = QPushButton("Save");   save.setObjectName("btn_primary")
        save.clicked.connect(self._save)
        btn_row.addWidget(cancel); btn_row.addWidget(save)
        layout.addLayout(btn_row)

    # ── Tab builders ─────────────────────────────────────────────────

    def _build_basic_tab(self) -> QWidget:
        w = QWidget(); form = QFormLayout(w); form.setSpacing(8)
        e = self._existing or {}

        self.flat_no = QLineEdit(e.get("flat_no") or "")
        self.flat_no.setPlaceholderText("e.g. 101, A-203, T2-805")
        self.flat_no.setFixedHeight(32)
        form.addRow(QLabel("Flat Number *"), self.flat_no)

        self.block = QLineEdit(e.get("block") or "")
        self.block.setFixedHeight(32)
        form.addRow(QLabel("Block"), self.block)

        self.tower = QLineEdit(e.get("tower") or "")
        self.tower.setFixedHeight(32)
        form.addRow(QLabel("Tower"), self.tower)

        self.floor = QLineEdit(e.get("floor") or "")
        self.floor.setFixedHeight(32)
        form.addRow(QLabel("Floor"), self.floor)

        self.flat_type = QComboBox()
        self.flat_type.setEditable(True)
        self.flat_type.addItems(_FLAT_TYPES)
        self.flat_type.setFixedHeight(32)
        if e.get("flat_type"):
            self.flat_type.setCurrentText(e["flat_type"])
        form.addRow(QLabel("Type"), self.flat_type)

        self.area = QDoubleSpinBox(); self.area.setRange(0, 99999)
        self.area.setDecimals(2); self.area.setSuffix(" sq ft")
        self.area.setFixedHeight(32)
        if e.get("area_sqft"): self.area.setValue(float(e["area_sqft"]))
        form.addRow(QLabel("Carpet Area"), self.area)

        self.built_up = QDoubleSpinBox(); self.built_up.setRange(0, 99999)
        self.built_up.setDecimals(2); self.built_up.setSuffix(" sq ft")
        self.built_up.setFixedHeight(32)
        if e.get("built_up_area_sqft"):
            self.built_up.setValue(float(e["built_up_area_sqft"]))
        form.addRow(QLabel("Built-up Area"), self.built_up)

        return w

    def _build_people_tab(self) -> QWidget:
        w = QWidget(); form = QFormLayout(w); form.setSpacing(8)
        e = self._existing or {}

        owners = self.owners.list_owners(active_only=True)

        self.primary_owner = QComboBox()
        self.primary_owner.setFixedHeight(32)
        self.primary_owner.addItem("(not set)", None)
        for o in owners:
            self.primary_owner.addItem(o["name"], o["id"])
        if e.get("primary_owner_id"):
            self._select_combo(self.primary_owner, e["primary_owner_id"])
        form.addRow(QLabel("Primary Owner"), self.primary_owner)

        self.primary_tenant = QComboBox()
        self.primary_tenant.setFixedHeight(32)
        self.primary_tenant.addItem("(none — owner-occupied)", None)
        for o in owners:
            self.primary_tenant.addItem(o["name"], o["id"])
        if e.get("primary_tenant_id"):
            self._select_combo(self.primary_tenant, e["primary_tenant_id"])
        form.addRow(QLabel("Primary Tenant"), self.primary_tenant)

        self.occupation = QComboBox(); self.occupation.setFixedHeight(32)
        for code in VALID_OCCUPATION:
            self.occupation.addItem(code.replace("_", " ").title(), code)
        if e.get("occupation_status"):
            self._select_combo(self.occupation, e["occupation_status"])
        else:
            self._select_combo(self.occupation, "OWNER_OCCUPIED")
        form.addRow(QLabel("Occupation"), self.occupation)

        self.bill_payer = QComboBox(); self.bill_payer.setFixedHeight(32)
        for code in VALID_BILL_PAYER:
            self.bill_payer.addItem(f"{code.title()} pays", code)
        if e.get("bill_payer"):
            self._select_combo(self.bill_payer, e["bill_payer"])
        else:
            self._select_combo(self.bill_payer, "OWNER")
        form.addRow(QLabel("Maintenance billed to"), self.bill_payer)

        hint = QLabel(
            "Bill chases whichever person you pick above. Their payment "
            "details (UPI / bank) come from their Member record."
        )
        hint.setWordWrap(True)
        hint.setStyleSheet(
            f"color:{THEME['text_secondary']}; font-size:10px;"
        )
        form.addRow("", hint)

        return w

    def _build_property_tab(self) -> QWidget:
        w = QWidget(); form = QFormLayout(w); form.setSpacing(8)
        e = self._existing or {}

        self.parking = QSpinBox(); self.parking.setRange(0, 10)
        self.parking.setFixedHeight(32)
        self.parking.setValue(int(e.get("parking_count") or 0))
        form.addRow(QLabel("Parking Slots"), self.parking)

        self.storage_no = QLineEdit(e.get("storage_no") or "")
        self.storage_no.setPlaceholderText("e.g. ST-12, Locker-A4")
        self.storage_no.setFixedHeight(32)
        form.addRow(QLabel("Storage / Locker"), self.storage_no)

        self.sale_deed = SmartDateEdit()
        self.sale_deed.setDisplayFormat("dd-MMM-yyyy")
        self.sale_deed.setFixedHeight(32)
        from PySide6.QtCore import QDate
        if e.get("sale_deed_date"):
            self.sale_deed.setDate(QDate.fromString(e["sale_deed_date"], "yyyy-MM-dd"))
        form.addRow(QLabel("Sale Deed Date"), self.sale_deed)

        self.possession = SmartDateEdit()
        self.possession.setDisplayFormat("dd-MMM-yyyy")
        self.possession.setFixedHeight(32)
        if e.get("possession_date"):
            self.possession.setDate(QDate.fromString(e["possession_date"], "yyyy-MM-dd"))
        form.addRow(QLabel("Possession Date"), self.possession)

        if e.get("ledger_id"):
            note = QLabel(
                f"💡 Companion ledger: <b>Flat {e['flat_no']}</b> "
                f"(under Sundry Debtors). Rename only allowed before "
                f"any voucher posts."
            )
            note.setStyleSheet(
                f"color:{THEME['text_secondary']}; font-size:10px;"
            )
            note.setWordWrap(True)
            form.addRow("", note)

        return w

    # ── Helpers ──────────────────────────────────────────────────────

    @staticmethod
    def _select_combo(combo: QComboBox, value) -> None:
        for i in range(combo.count()):
            if combo.itemData(i) == value:
                combo.setCurrentIndex(i)
                return

    # ── Save ─────────────────────────────────────────────────────────

    def _save(self):
        # Commit any in-flight edits
        for w in (self.flat_no, self.block, self.tower, self.floor,
                  self.storage_no):
            try: w.clearFocus()
            except Exception: pass
        for w in (self.area, self.built_up, self.parking):
            try: w.interpretText()
            except Exception: pass

        from PySide6.QtCore import QDate

        def _iso(date_edit) -> str | None:
            d = date_edit.date()
            if not d.isValid() or d.year() < 1990:
                return None
            return d.toString("yyyy-MM-dd")

        try:
            kwargs = dict(
                flat_no=self.flat_no.text().strip(),
                block=self.block.text().strip(),
                tower=self.tower.text().strip(),
                floor=self.floor.text().strip(),
                flat_type=self.flat_type.currentText().strip(),
                area_sqft=self.area.value() or None,
                built_up_area_sqft=self.built_up.value() or None,
                parking_count=int(self.parking.value()),
                storage_no=self.storage_no.text().strip(),
                occupation_status=self.occupation.currentData(),
                bill_payer=self.bill_payer.currentData(),
                sale_deed_date=_iso(self.sale_deed),
                possession_date=_iso(self.possession),
            )

            primary_owner_id  = self.primary_owner.currentData()
            primary_tenant_id = self.primary_tenant.currentData()

            if self.flat_id:
                # Update path
                self.flats.update_flat(self.flat_id, **kwargs)
                if primary_owner_id is not None:
                    self.flats.set_primary_owner(self.flat_id, primary_owner_id)
                self.flats.set_primary_tenant(self.flat_id, primary_tenant_id)
            else:
                # Add path — create the flat first to get an id, then
                # assign owner/tenant pointers (which also create the
                # rwa_flat_owners link rows).
                new_id = self.flats.add_flat(**kwargs)
                if primary_owner_id is not None:
                    self.flats.set_primary_owner(new_id, primary_owner_id)
                if primary_tenant_id is not None:
                    self.flats.set_primary_tenant(new_id, primary_tenant_id)

        except ValueError as e:
            QMessageBox.warning(self, "Cannot save", str(e))
            return
        except Exception as e:
            QMessageBox.critical(self, "Error", str(e))
            return

        self.saved.emit()
        self.accept()


class FlatsPage(QWidget):
    """Master list of flats. Filter + sortable headers + outstanding-
    dues column (computed via FlatsService.outstanding_balance_for_flats —
    single SQL, scales to thousands of flats)."""

    def __init__(self, db, company_id: int, tree, parent=None):
        self.db = db
        self.company_id = company_id
        self.tree = tree
        super().__init__(parent)
        self.flats  = FlatsService(db, company_id, tree)
        self.owners = OwnersService(db, company_id)
        self._build_ui()
        self.refresh()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 16, 24, 24)
        layout.setSpacing(10)

        title = QLabel("Flats")
        title.setObjectName("page_title")
        layout.addWidget(title)
        sub = QLabel(
            "All flats / units in the society. Each flat has its own "
            "ledger under Sundry Debtors for maintenance billing."
        )
        sub.setObjectName("page_subtitle")
        layout.addWidget(sub)

        # Toolbar
        bar = QFrame(); bar.setObjectName("card")
        bar_l = QHBoxLayout(bar)
        bar_l.setContentsMargins(10, 6, 10, 6); bar_l.setSpacing(8)

        self.filter_edit = QLineEdit()
        self.filter_edit.setPlaceholderText(
            "🔍 Filter by flat no / block / owner / tenant…"
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

        add_btn = QPushButton("+ Add Flat")
        add_btn.setObjectName("btn_primary"); add_btn.setFixedHeight(30)
        add_btn.clicked.connect(self._on_add)
        bar_l.addWidget(add_btn)

        edit_btn = QPushButton("Edit")
        edit_btn.setFixedHeight(30); edit_btn.clicked.connect(self._on_edit)
        bar_l.addWidget(edit_btn)

        layout.addWidget(bar)

        # Table — new columns: Tenant, Bill Payer, Outstanding
        self.table = QTableWidget(0, 9)
        self.table.setHorizontalHeaderLabels([
            "Flat #", "Block", "Type", "Area",
            "Owner", "Tenant", "Bill Payer",
            "Outstanding", "Status",
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
        hdr.setSectionResizeMode(0, QHeaderView.ResizeMode.Interactive)
        hdr.setSectionResizeMode(4, QHeaderView.ResizeMode.Stretch)
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
        flats = self.flats.list_flats(
            active_only=not self.show_inactive.isChecked()
        )
        # One bulk SQL for all outstandings.
        balances = self.flats.outstanding_balance_for_flats(
            [f["id"] for f in flats]
        )
        total_dues = 0.0

        self.table.setRowCount(len(flats))
        for r, f in enumerate(flats):
            name_item = QTableWidgetItem(f["flat_no"] or "")
            name_item.setData(Qt.ItemDataRole.UserRole, f["id"])
            self.table.setItem(r, 0, name_item)
            self.table.setItem(r, 1, QTableWidgetItem(f.get("block") or ""))
            self.table.setItem(r, 2, QTableWidgetItem(f.get("flat_type") or ""))
            area = f.get("built_up_area_sqft") or f.get("area_sqft")
            self.table.setItem(r, 3, QTableWidgetItem(
                f"{area:,.0f}" if area else ""
            ))
            self.table.setItem(r, 4, QTableWidgetItem(
                f.get("primary_owner_name") or "—"
            ))
            self.table.setItem(r, 5, QTableWidgetItem(
                f.get("primary_tenant_name") or "—"
            ))
            self.table.setItem(r, 6, QTableWidgetItem(
                (f.get("bill_payer") or "OWNER").title()
            ))

            # Outstanding — show only when positive and side is Dr
            # (the flat owes money). Other side means an overpayment.
            bal = balances.get(f["id"])
            if bal and bal["balance"] > 0.01:
                amt = bal["balance"]
                side = bal["type"]
                out_item = QTableWidgetItem(
                    f"₹ {amt:,.2f}" + (" (advance)" if side == "Cr" else "")
                )
                if side == "Dr":
                    out_item.setForeground(QColor(THEME["danger"]))
                    total_dues += amt
                else:
                    out_item.setForeground(QColor(THEME["success"]))
            else:
                out_item = QTableWidgetItem("")
            self.table.setItem(r, 7, out_item)

            occ = (f.get("occupation_status") or "OWNER_OCCUPIED")
            status_text = occ.replace("_", "-").title()
            if not f.get("active"):
                status_text = "Inactive"
            status_item = QTableWidgetItem(status_text)
            if not f.get("active"):
                status_item.setForeground(QColor(THEME["text_dim"]))
            elif occ == "VACANT":
                status_item.setForeground(QColor(THEME["warning"]))
            self.table.setItem(r, 8, status_item)

        self.table.setSortingEnabled(True)
        self._apply_filter(self.filter_edit.text())
        self.summary.setText(
            f"{len(flats)} flat(s)  ·  Total outstanding: ₹ {total_dues:,.2f}"
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

    def _selected_flat_id(self) -> int | None:
        row = self.table.currentRow()
        if row < 0: return None
        item = self.table.item(row, 0)
        return item.data(Qt.ItemDataRole.UserRole) if item else None

    def _on_add(self):
        dlg = _FlatDialog(self.flats, self.owners, flat_id=None, parent=self)
        dlg.saved.connect(self.refresh)
        dlg.exec()

    def _on_edit(self, *_):
        fid = self._selected_flat_id()
        if not fid:
            QMessageBox.information(
                self, "No flat selected",
                "Pick a row first, then click Edit.",
            )
            return
        dlg = _FlatDialog(self.flats, self.owners, flat_id=fid, parent=self)
        dlg.saved.connect(self.refresh)
        dlg.exec()
