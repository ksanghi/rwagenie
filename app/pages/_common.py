"""
Tiny helpers shared across RWA pages.

Each page builds its own table — different columns, different actions —
but the visual styling (row height, padding, sortable headers, etc.)
is identical. Keeping that in one place so a styling tweak lands
everywhere at once.
"""
from __future__ import annotations

from PySide6.QtCore    import Qt
from PySide6.QtWidgets import (
    QTableWidget, QHeaderView, QAbstractItemView,
)

from app.theme import THEME


def style_table(table: QTableWidget, *, stretch_cols: list[int] | None = None) -> None:
    """Apply the standard RWA table look: dense rows, 2/8 cell padding
    override (otherwise the global stylesheet's 8/12 makes everything
    too tall), sortable headers, alternating row colours."""
    table.verticalHeader().setVisible(False)
    table.setAlternatingRowColors(True)
    table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
    table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
    table.setSortingEnabled(True)
    table.verticalHeader().setDefaultSectionSize(30)
    table.setStyleSheet(
        "QTableWidget::item { padding: 2px 8px; }"
        "QHeaderView::section { padding: 4px 8px; }"
    )
    if stretch_cols:
        hdr = table.horizontalHeader()
        for c in stretch_cols:
            hdr.setSectionResizeMode(c, QHeaderView.ResizeMode.Stretch)


def apply_text_filter(table: QTableWidget, text: str) -> None:
    """Hide rows where no column contains the given case-insensitive
    substring. Empty filter shows all."""
    needle = (text or "").strip().lower()
    for r in range(table.rowCount()):
        if not needle:
            table.setRowHidden(r, False)
            continue
        hit = False
        for c in range(table.columnCount()):
            item = table.item(r, c)
            if item and needle in (item.text() or "").lower():
                hit = True
                break
        table.setRowHidden(r, not hit)


def chip_label(text: str, color: str) -> str:
    """Build a small HTML chip for status/priority columns.
    Note: QTableWidgetItem doesn't render HTML — use as raw text for now,
    or upgrade to setCellWidget(QLabel) per cell if we want real chips."""
    return text   # placeholder; real chip rendering can come later
