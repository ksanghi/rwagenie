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
    QDialog, QFormLayout, QComboBox, QDoubleSpinBox, QMessageBox,
    QSizePolicy, QFrame,
)
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui  import QColor

from app.theme import THEME            # RWAGenie theme (mirrors AG for v0.1)
from ui.widgets import SmartDateEdit   # generic widget, sibling-imported from AG
from app.services import FlatsService, OwnersService


class _FlatDialog(QDialog):
    """Add / edit a single flat. Used in both modes — pass flat_id=None
    for add."""
    saved = Signal()

    def __init__(self, service: FlatsService, flat_id: int | None = None,
                 parent=None):
        super().__init__(parent)
        self.service = service
        self.flat_id = flat_id
        self.setWindowTitle("Edit Flat" if flat_id else "Add Flat")
        self.setMinimumWidth(440)
        self.setModal(True)

        existing = self.service.get_flat(flat_id) if flat_id else None

        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        layout.setContentsMargins(20, 20, 20, 20)

        hdr = QLabel("✎ Edit Flat" if existing else "+ Add Flat")
        hdr.setStyleSheet(
            f"font-size:14px; font-weight:bold; color:{THEME['accent']};"
        )
        layout.addWidget(hdr)

        form = QFormLayout()
        form.setSpacing(10)

        self.flat_no = QLineEdit(existing["flat_no"] if existing else "")
        self.flat_no.setPlaceholderText("e.g. 101, A-203, T2-805")
        self.flat_no.setFixedHeight(34)
        form.addRow(QLabel("Flat Number *"), self.flat_no)

        self.block = QLineEdit((existing or {}).get("block") or "")
        self.block.setPlaceholderText("optional")
        self.block.setFixedHeight(34)
        form.addRow(QLabel("Block"), self.block)

        self.tower = QLineEdit((existing or {}).get("tower") or "")
        self.tower.setPlaceholderText("optional")
        self.tower.setFixedHeight(34)
        form.addRow(QLabel("Tower"), self.tower)

        self.floor = QLineEdit((existing or {}).get("floor") or "")
        self.floor.setPlaceholderText("optional")
        self.floor.setFixedHeight(34)
        form.addRow(QLabel("Floor"), self.floor)

        self.area = QDoubleSpinBox()
        self.area.setRange(0, 99999)
        self.area.setDecimals(2)
        self.area.setSuffix(" sq ft")
        self.area.setFixedHeight(34)
        if existing and existing.get("area_sqft"):
            self.area.setValue(float(existing["area_sqft"]))
        form.addRow(QLabel("Area"), self.area)

        self.ownership = QComboBox()
        self.ownership.addItems(["OWNED", "RENTED", "VACANT"])
        self.ownership.setFixedHeight(34)
        if existing:
            ix = self.ownership.findText(
                (existing.get("ownership_type") or "OWNED").upper()
            )
            if ix >= 0:
                self.ownership.setCurrentIndex(ix)
        form.addRow(QLabel("Ownership"), self.ownership)

        layout.addLayout(form)

        if existing and existing.get("ledger_id"):
            note = QLabel(
                f"💡 Companion ledger: "
                f"<b>Flat {existing['flat_no']}</b> "
                f"(under Sundry Debtors). "
                f"Rename only allowed before any voucher posts against it."
            )
            note.setStyleSheet(
                f"color:{THEME['text_secondary']}; font-size:10px;"
            )
            note.setWordWrap(True)
            layout.addWidget(note)

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
        # Commit any in-flight focus edits before reading values.
        for w in (self.flat_no, self.block, self.tower, self.floor):
            try:
                w.clearFocus()
            except Exception:
                pass
        try:
            self.area.interpretText()
        except Exception:
            pass

        try:
            if self.flat_id:
                self.service.update_flat(
                    self.flat_id,
                    flat_no=self.flat_no.text().strip(),
                    block=self.block.text().strip(),
                    tower=self.tower.text().strip(),
                    floor=self.floor.text().strip(),
                    area_sqft=self.area.value() or None,
                    ownership_type=self.ownership.currentText(),
                )
            else:
                self.service.add_flat(
                    flat_no=self.flat_no.text().strip(),
                    block=self.block.text().strip(),
                    tower=self.tower.text().strip(),
                    floor=self.floor.text().strip(),
                    area_sqft=self.area.value() or None,
                    ownership_type=self.ownership.currentText(),
                )
        except ValueError as e:
            QMessageBox.warning(self, "Cannot save", str(e))
            return
        except Exception as e:
            QMessageBox.critical(self, "Error", str(e))
            return
        self.saved.emit()
        self.accept()


class FlatsPage(QWidget):
    """Master list of flats. Filter + sortable headers built in."""

    def __init__(self, db, company_id: int, tree, parent=None):
        super().__init__(parent)
        self.service = FlatsService(db, company_id, tree)
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

        # Toolbar: filter + actions
        bar = QFrame()
        bar.setObjectName("card")
        bar_l = QHBoxLayout(bar)
        bar_l.setContentsMargins(10, 6, 10, 6)
        bar_l.setSpacing(8)

        self.filter_edit = QLineEdit()
        self.filter_edit.setPlaceholderText(
            "🔍 Filter by flat no / block / tower / owner…"
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
        add_btn.setObjectName("btn_primary")
        add_btn.setFixedHeight(30)
        add_btn.clicked.connect(self._on_add)
        bar_l.addWidget(add_btn)

        edit_btn = QPushButton("Edit")
        edit_btn.setFixedHeight(30)
        edit_btn.clicked.connect(self._on_edit)
        bar_l.addWidget(edit_btn)

        layout.addWidget(bar)

        # Table
        self.table = QTableWidget(0, 8)
        self.table.setHorizontalHeaderLabels([
            "Flat #", "Block", "Tower", "Floor", "Area (sq ft)",
            "Ownership", "Primary Owner", "Status",
        ])
        self.table.verticalHeader().setVisible(False)
        self.table.setAlternatingRowColors(True)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSortingEnabled(True)   # click headers to sort
        self.table.verticalHeader().setDefaultSectionSize(30)
        self.table.setStyleSheet(
            "QTableWidget::item { padding: 2px 8px; }"
            "QHeaderView::section { padding: 4px 8px; }"
        )
        hdr = self.table.horizontalHeader()
        hdr.setSectionResizeMode(0, QHeaderView.ResizeMode.Interactive)
        hdr.setSectionResizeMode(6, QHeaderView.ResizeMode.Stretch)
        self.table.doubleClicked.connect(self._on_edit)
        layout.addWidget(self.table, 1)

        self.summary = QLabel("")
        self.summary.setStyleSheet(
            f"color:{THEME['text_secondary']}; font-size:11px; padding:4px;"
        )
        layout.addWidget(self.summary)

    def refresh(self):
        # setSortingEnabled must be off while populating, else inserted
        # rows get auto-sorted into the wrong slot.
        self.table.setSortingEnabled(False)
        flats = self.service.list_flats(
            active_only=not self.show_inactive.isChecked()
        )
        self.table.setRowCount(len(flats))
        for r, f in enumerate(flats):
            name_item = QTableWidgetItem(f["flat_no"] or "")
            name_item.setData(Qt.ItemDataRole.UserRole, f["id"])
            self.table.setItem(r, 0, name_item)
            self.table.setItem(r, 1, QTableWidgetItem(f.get("block") or ""))
            self.table.setItem(r, 2, QTableWidgetItem(f.get("tower") or ""))
            self.table.setItem(r, 3, QTableWidgetItem(f.get("floor") or ""))
            area = f.get("area_sqft")
            self.table.setItem(r, 4, QTableWidgetItem(
                f"{area:,.0f}" if area else ""
            ))
            self.table.setItem(r, 5, QTableWidgetItem(
                (f.get("ownership_type") or "").title()
            ))
            self.table.setItem(r, 6, QTableWidgetItem(
                f.get("primary_owner") or "—"
            ))
            status_item = QTableWidgetItem(
                "Active" if f.get("active") else "Inactive"
            )
            if not f.get("active"):
                status_item.setForeground(QColor(THEME["text_dim"]))
            self.table.setItem(r, 7, status_item)
        self.table.setSortingEnabled(True)
        self._apply_filter(self.filter_edit.text())
        self.summary.setText(
            f"{len(flats)} flat(s)"
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
        if row < 0:
            return None
        item = self.table.item(row, 0)
        if not item:
            return None
        return item.data(Qt.ItemDataRole.UserRole)

    def _on_add(self):
        dlg = _FlatDialog(self.service, flat_id=None, parent=self)
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
        dlg = _FlatDialog(self.service, flat_id=fid, parent=self)
        dlg.saved.connect(self.refresh)
        dlg.exec()
