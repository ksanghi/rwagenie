"""
Placeholder widget for RWA pages that have a schema and a sidebar entry
but no UI yet. Lets us register every Free-tier feature in the sidebar
from v0.1 onward so the user sees the full intended surface.
"""
from __future__ import annotations

from PySide6.QtWidgets import QWidget, QVBoxLayout, QLabel, QFrame
from PySide6.QtCore    import Qt

from app.theme import THEME


class ComingSoonPage(QWidget):
    """Generic 'Coming in a near build' placeholder. Pass the feature
    name + a one-line description into the constructor."""

    def __init__(self, feature_name: str, blurb: str, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(40, 60, 40, 60)
        layout.setSpacing(16)

        title = QLabel(f"{feature_name} — coming soon")
        title.setObjectName("page_title")
        title.setStyleSheet(
            f"color:{THEME['accent']}; font-size:22px; font-weight:bold;"
        )
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title)

        sub = QLabel(blurb)
        sub.setStyleSheet(
            f"color:{THEME['text_secondary']}; font-size:14px;"
        )
        sub.setWordWrap(True)
        sub.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(sub)

        card = QFrame()
        card.setObjectName("card")
        card.setStyleSheet(
            f"background:{THEME['bg_card']}; border-radius:10px; "
            f"padding:24px;"
        )
        cl = QVBoxLayout(card)
        info = QLabel(
            "<b>v0.1 ships with:</b> Flats master + Member directory.<br>"
            "<br>"
            "<b>Next iteration:</b> the page you clicked plus 4 more "
            "(Notice Board, Complaints, Broadcasts, Polls, Visitor "
            "Pass). Schemas already exist in the company database, so "
            "no migration friction when the pages land."
        )
        info.setStyleSheet(
            f"color:{THEME['text_primary']}; font-size:13px;"
        )
        info.setWordWrap(True)
        info.setAlignment(Qt.AlignmentFlag.AlignCenter)
        cl.addWidget(info)
        layout.addWidget(card)

        layout.addStretch()
