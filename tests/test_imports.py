"""
Smoke test for the RWAGenie module layout.

Verifies:
  - main.py bootstraps PYTHONPATH to find the sibling AG repo.
  - core.models and core.account_tree are importable through that path.
  - app/* modules parse and import without Qt running.

Run with:   python -m unittest tests.test_imports -v
"""
from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path


class TestRWAGenieImports(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        repo = Path(__file__).resolve().parent.parent
        ag   = repo.parent / "Aiccounting"
        # Mirror main.py's path bootstrap.
        sys.path.insert(0, str(repo))
        if ag.is_dir():
            sys.path.insert(0, str(ag))

    def test_ag_engine_importable(self):
        from core.models       import Database              # noqa
        from core.account_tree import AccountTree           # noqa
        from core.voucher_engine import VoucherEngine       # noqa

    def test_rwa_modules_importable(self):
        from app          import PRODUCT_NAME, __version__
        self.assertEqual(PRODUCT_NAME, "RWAGenie")
        self.assertTrue(__version__)

        from app.theme    import THEME, get_stylesheet
        self.assertIn("accent", THEME)

        from app.models   import apply_rwa_schema   # noqa
        from app.services import FlatsService, OwnersService  # noqa

    def test_pages_parse(self):
        # Importing the page modules pulls in their imports (Qt classes
        # via PySide6, app.theme, app.services). We don't instantiate
        # the widgets — that'd need a QApplication. Just import-checks.
        from app.pages import flats_page    # noqa
        from app.pages import members_page  # noqa

    def test_rwa_schema_idempotent(self):
        """apply_rwa_schema should run twice without error on a fresh DB."""
        import tempfile
        from core.models import Database

        with tempfile.TemporaryDirectory() as tmp:
            # Patch the AG companies_dir to point at our temp.
            import core.models as _m
            old_dir = _m.DB_DIR
            try:
                _m.DB_DIR = Path(tmp)
                # Patch companies_dir too
                from core import paths
                paths.companies_dir = lambda: Path(tmp)

                db = Database("rwa_smoke")
                cur = db.execute(
                    "INSERT INTO companies (name, gstin, state_code) VALUES (?,?,?)",
                    ("Test Society", "", "07"),
                )
                db.commit()

                from app.models import apply_rwa_schema
                apply_rwa_schema(db)
                apply_rwa_schema(db)  # second call must not blow up

                # Verify the tables exist
                rows = db.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' "
                    "AND name LIKE 'rwa_%'"
                ).fetchall()
                table_names = {r["name"] for r in rows}
                self.assertIn("rwa_flats", table_names)
                self.assertIn("rwa_owners", table_names)
                self.assertIn("rwa_flat_owners", table_names)
                db.close()
            finally:
                _m.DB_DIR = old_dir


if __name__ == "__main__":
    unittest.main()
