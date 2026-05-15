"""
RWAGenie Company Dialog.

Equivalent to AccGenie's CompanyDialog but with RWA branding /
terminology (a 'company' is a 'society' in RWA-speak). Operates on
the same underlying company DB layout — RWAGenie and AccGenie share
the .db files so a society can use either app to view the same data.

Why a separate dialog rather than import AG's:
  AG's CompanyDialog lives in AG/main.py. With both repos on
  sys.path (rwagenie at index 0), `from main import CompanyDialog`
  resolves to rwagenie/main.py (the shim), which doesn't define
  CompanyDialog → ImportError. Could be worked around with
  importlib.util.spec_from_file_location, but cleaner to own our
  own dialog so the v0.1 surface is RWA-branded end-to-end.
"""
from __future__ import annotations

from PySide6.QtCore    import Qt
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QLineEdit,
    QComboBox, QFormLayout, QFrame, QMessageBox,
)

from core.models       import Database
from core.account_tree import AccountTree

from app          import PRODUCT_NAME
from app.theme    import THEME, get_stylesheet


class CompanyDialog(QDialog):
    """Pick an existing society, or create a new one."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"{PRODUCT_NAME} — Open Society")
        self.setMinimumWidth(460)
        self.setMinimumHeight(320)
        self.setStyleSheet(get_stylesheet())
        self.selected_db   = None
        self.selected_cid  = None
        self.selected_tree = None
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(14)
        layout.setContentsMargins(24, 24, 24, 24)

        # Brand header — text only for v0.1; real logo lands later.
        brand = QLabel(PRODUCT_NAME)
        brand.setStyleSheet(
            f"color:{THEME['accent']}; font-size:32px; font-weight:bold;"
        )
        brand.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(brand)

        tagline = QLabel("Resident Welfare Association management")
        tagline.setStyleSheet(
            f"color:{THEME['text_secondary']}; font-size:12px;"
        )
        tagline.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(tagline)

        sep = QFrame(); sep.setFrameShape(QFrame.Shape.HLine)
        layout.addWidget(sep)

        # Existing societies
        existing = self._get_existing()
        if existing:
            open_lbl = QLabel("Open existing society")
            open_lbl.setStyleSheet(
                f"color:{THEME['text_secondary']}; font-size:11px; font-weight:bold;"
            )
            layout.addWidget(open_lbl)

            self.company_combo = QComboBox()
            self.company_combo.setFixedHeight(34)
            for slug, name in existing:
                self.company_combo.addItem(name, slug)
            layout.addWidget(self.company_combo)

            open_btn = QPushButton("Open")
            open_btn.setObjectName("btn_primary")
            open_btn.setFixedHeight(36)
            open_btn.clicked.connect(self._open_existing)
            layout.addWidget(open_btn)

            sep2 = QFrame(); sep2.setFrameShape(QFrame.Shape.HLine)
            layout.addWidget(sep2)

        # Create new
        new_lbl = QLabel(
            "Create new society" if existing else "Set up your society"
        )
        new_lbl.setStyleSheet(
            f"color:{THEME['text_secondary']}; font-size:11px; font-weight:bold;"
        )
        layout.addWidget(new_lbl)

        form = QFormLayout()
        form.setSpacing(8)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)

        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText("e.g. Sunshine Apartments CHS")
        self.name_edit.setFixedHeight(34)
        form.addRow(QLabel("Society Name *"), self.name_edit)

        self.gstin_edit = QLineEdit()
        self.gstin_edit.setPlaceholderText("Optional — society GSTIN if registered")
        self.gstin_edit.setFixedHeight(34)
        form.addRow(QLabel("GSTIN"), self.gstin_edit)

        self.state_edit = QLineEdit("27")
        self.state_edit.setFixedHeight(34)
        self.state_edit.setMaximumWidth(60)
        form.addRow(QLabel("State Code"), self.state_edit)

        layout.addLayout(form)

        btn_row = QHBoxLayout()
        create_btn = QPushButton("Create & Open")
        create_btn.setObjectName("btn_primary")
        create_btn.setFixedHeight(36)
        create_btn.clicked.connect(self._create_company)
        btn_row.addWidget(create_btn)
        layout.addLayout(btn_row)

        self.name_edit.returnPressed.connect(self._create_company)

    def _get_existing(self):
        """List every company .db file under the user-data dir, with its
        first-row 'name' as the display label. Shared with AccGenie —
        an AG company appears here too (and vice versa)."""
        from core.paths import companies_dir
        db_dir = companies_dir()
        result = []
        if not db_dir.exists():
            return result
        for f in sorted(db_dir.glob("*.db")):
            try:
                db_tmp = Database(f.stem)
                row = db_tmp.execute(
                    "SELECT name FROM companies LIMIT 1"
                ).fetchone()
                if row:
                    result.append((f.stem, row["name"]))
                db_tmp.close()
            except Exception:
                pass
        return result

    def _open_existing(self):
        slug = self.company_combo.currentData()
        try:
            db = Database(slug)
            row = db.execute("SELECT id FROM companies LIMIT 1").fetchone()
            if not row:
                QMessageBox.warning(self, "Error", "Society data not found.")
                return
            company_id = row["id"]
            tree = AccountTree(db, company_id)
            self.selected_db   = db
            self.selected_cid  = company_id
            self.selected_tree = tree
            self.accept()
        except Exception as e:
            QMessageBox.critical(self, "Error", str(e))

    def _create_company(self):
        name = self.name_edit.text().strip()
        if not name:
            self.name_edit.setStyleSheet(
                f"border: 1px solid {THEME['danger']};"
            )
            return

        gstin      = self.gstin_edit.text().strip()
        state_code = self.state_edit.text().strip() or "27"
        if gstin and len(gstin) >= 2:
            state_code = gstin[:2]

        slug = name.lower()
        for ch in " .,()&'\"":
            slug = slug.replace(ch, "_")
        slug = slug[:30].strip("_")

        try:
            db   = Database(slug)
            conn = db.connect()
            conn.execute(
                "INSERT OR IGNORE INTO companies "
                "(name, gstin, state_code) VALUES (?,?,?)",
                (name, gstin, state_code),
            )
            db.commit()

            row = conn.execute(
                "SELECT id FROM companies WHERE name=?", (name,),
            ).fetchone()
            company_id = row["id"]

            # Default FY
            conn.execute(
                "INSERT OR IGNORE INTO financial_years "
                "(company_id, fy, start_date, end_date) VALUES (?,?,?,?)",
                (company_id, "2025-26", "2025-04-01", "2026-03-31"),
            )
            db.commit()

            # Seed AG chart of accounts (Sundry Debtors, Bank Accounts, etc.)
            tree = AccountTree(db, company_id)
            tree.seed_defaults()

            self.selected_db   = db
            self.selected_cid  = company_id
            self.selected_tree = tree
            self.accept()
        except Exception as e:
            QMessageBox.critical(self, "Error", str(e))
