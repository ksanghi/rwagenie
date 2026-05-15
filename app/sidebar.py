"""
Collapsible sidebar sections for RWAGenie.

AG's `MainWindow` renders the sidebar linearly — `register_page()` adds
each NavButton plus an optional section label at the bottom of the
list. With AG's existing pages + RWA's new pages, the sidebar runs
30+ entries deep on a normal screen. Too much.

This module post-processes that linear layout into collapsible groups:

  ▾ RWA            ← expanded by default
        Flats
        Members
        Notice Board
        …
  ▸ Accounting     ← collapsed
  ▸ Reports        ← collapsed
  …

The actual NavButton widgets are reused (re-parented), so navigation
clicks still route to the right page through AG's existing
_select_page() callback wiring.
"""
from __future__ import annotations

from PySide6.QtCore    import Qt
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QPushButton, QSizePolicy,
)

from app.theme import THEME


class CollapsibleSection(QWidget):
    """One section in the RWAGenie sidebar: a clickable header that
    shows/hides a stack of child buttons.

    Doesn't try to animate the height — Qt animation on QSS-styled
    widgets stutters and the user wants speed over polish here.
    """

    def __init__(self, title: str, expanded: bool = False, parent=None):
        super().__init__(parent)
        self._title    = title
        self._expanded = expanded

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 4, 0, 0)
        outer.setSpacing(0)

        self._header = QPushButton()
        self._header.setFixedHeight(28)
        self._header.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed,
        )
        self._header.clicked.connect(self.toggle)
        outer.addWidget(self._header)

        self._body = QWidget()
        self._body_layout = QVBoxLayout(self._body)
        self._body_layout.setContentsMargins(0, 0, 0, 0)
        self._body_layout.setSpacing(0)
        outer.addWidget(self._body)

        self._apply_state()

    # ── API for the host ──────────────────────────────────────────────────────

    def add_button(self, button: QWidget) -> None:
        """Re-parent an existing NavButton into this section's body."""
        button.setParent(self._body)
        self._body_layout.addWidget(button)

    def is_empty(self) -> bool:
        return self._body_layout.count() == 0

    def set_expanded(self, value: bool) -> None:
        self._expanded = bool(value)
        self._apply_state()

    def toggle(self) -> None:
        self.set_expanded(not self._expanded)

    # ── Rendering ─────────────────────────────────────────────────────────────

    def _apply_state(self) -> None:
        self._body.setVisible(self._expanded)
        arrow = "▾" if self._expanded else "▸"
        self._header.setText(f"  {arrow}   {self._title.upper()}")
        # Header style mirrors the existing "nav_section" labels AG uses
        # for section headers, but clickable.
        self._header.setStyleSheet(f"""
            QPushButton {{
                background: transparent;
                border: none;
                color: {THEME['text_secondary']};
                font-size: 10px;
                font-weight: bold;
                letter-spacing: 1px;
                text-align: left;
                padding: 6px 14px;
            }}
            QPushButton:hover {{
                color: {THEME['accent']};
            }}
        """)


# ── Sidebar categorisation ───────────────────────────────────────────────────
#
# Map AG page labels (the string passed to register_page) to a section
# name. The match is case-insensitive substring — defensive against
# minor wording drift between AG releases.
#
# Anything not matched lands in "Other" so we never drop a page.

_LABEL_TO_SECTION: list[tuple[str, str]] = [
    # RWA (RWAGenie's own pages, registered by RWAMainWindow)
    ("Flats",            "RWA"),
    ("Members",          "RWA"),
    ("Notice Board",     "RWA"),
    ("Complaints",       "RWA"),
    ("Broadcasts",       "RWA"),
    ("Polls",            "RWA"),
    ("Visitor Pass",     "RWA"),

    # Accounting — daily-use entry surface
    ("Post Voucher",     "Accounting"),
    ("Day Book",         "Accounting"),
    ("Ledger Balances",  "Accounting"),
    ("Verbal Entry",     "Accounting"),
    ("Bank Reconciliation",  "Accounting"),
    ("Ledger Reconciliation","Accounting"),

    # Reports
    ("Trial Balance",    "Reports"),
    ("P & L",            "Reports"),
    ("Balance Sheet",    "Reports"),
    ("Cash Book",        "Reports"),
    ("Bank Book",        "Reports"),
    ("Ledger Account",   "Reports"),
    ("Rcpts & Pmts",     "Reports"),

    # Tax
    ("GST",              "Tax"),
    ("TDS",              "Tax"),

    # Data & tools
    ("Backup",           "Data"),
    ("Book Migration",   "Data"),
    ("AI Document",      "Data"),
    ("Period Lock",      "Data"),

    # Settings
    ("License",          "Settings"),
    ("Settings",         "Settings"),
    ("Feedback",         "Settings"),
]

# Section order on the sidebar, top to bottom. RWA first + expanded.
SECTION_ORDER: list[tuple[str, bool]] = [
    ("RWA",        True),    # expanded
    ("Accounting", False),
    ("Reports",    False),
    ("Tax",        False),
    ("Data",       False),
    ("Settings",   False),
    ("Other",      False),   # safety net; usually empty
]


def section_for_label(label: str) -> str:
    """Best-effort section lookup. Returns 'Other' if nothing matches."""
    lower = (label or "").lower()
    for needle, section in _LABEL_TO_SECTION:
        if needle.lower() in lower:
            return section
    return "Other"
