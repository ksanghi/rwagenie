"""
LoginDialog — shown right after the user picks a society.

Returns an AuthSession on accept; the caller (app/main.py) then
hands it to RWAMainWindow which uses it to gate features and
records actions to the audit log.

On a fresh society DB the UserService seeds an admin/admin user and
the dialog calls that out in a one-time banner so the new admin
knows the default credentials. The Users page nags them to change
the password.
"""
from __future__ import annotations

from typing import Optional

from PySide6.QtCore    import Qt
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QFormLayout, QLabel,
    QLineEdit, QPushButton, QFrame, QMessageBox,
)

from app          import PRODUCT_NAME
from app.theme    import THEME, get_stylesheet
from app.services.auth import (
    AuthSession, UserService,
    SEED_ADMIN_USERNAME, SEED_ADMIN_PASSWORD,
)


class LoginDialog(QDialog):
    """Block until the user authenticates, or they Cancel."""

    def __init__(self, db, company_id: int, company_name: str = "",
                 parent=None):
        super().__init__(parent)
        self.users      = UserService(db, company_id)
        self.session: Optional[AuthSession] = None

        self.setWindowTitle(f"{PRODUCT_NAME} — Sign in")
        self.setMinimumWidth(420)
        self.setStyleSheet(get_stylesheet())

        # Seed admin/admin on a brand-new DB so the user can always
        # get in. The returned flag drives the banner below.
        self._seeded = self.users.seed_default_admin_if_empty()

        self._build_ui(company_name)

    def _build_ui(self, company_name: str) -> None:
        layout = QVBoxLayout(self)
        layout.setSpacing(14)
        layout.setContentsMargins(24, 24, 24, 24)

        brand = QLabel(PRODUCT_NAME)
        brand.setStyleSheet(
            f"color:{THEME['accent']}; font-size:24px; font-weight:bold;"
        )
        brand.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(brand)

        if company_name:
            co = QLabel(company_name)
            co.setAlignment(Qt.AlignmentFlag.AlignCenter)
            co.setStyleSheet(
                f"color:{THEME['text_secondary']}; font-size:12px;"
            )
            layout.addWidget(co)

        sep = QFrame(); sep.setFrameShape(QFrame.Shape.HLine)
        layout.addWidget(sep)

        if self._seeded:
            banner = QLabel(
                f"🆕 First sign-in for this society. A default admin "
                f"login has been created:\n\n"
                f"    Username: <b>{SEED_ADMIN_USERNAME}</b>\n"
                f"    Password: <b>{SEED_ADMIN_PASSWORD}</b>\n\n"
                f"Please change the password from the Users page "
                f"after signing in."
            )
            banner.setWordWrap(True)
            banner.setStyleSheet(
                f"color:{THEME['warning']}; font-size:11px;"
                f" background:{THEME.get('bg_hover','#334155')};"
                f" padding:10px; border-radius:6px;"
            )
            layout.addWidget(banner)

        form = QFormLayout(); form.setSpacing(10)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)

        self.username = QLineEdit()
        self.username.setFixedHeight(34)
        self.username.setPlaceholderText(
            SEED_ADMIN_USERNAME if self._seeded else "Your username"
        )
        form.addRow(QLabel("Username"), self.username)

        self.password = QLineEdit()
        self.password.setFixedHeight(34)
        self.password.setEchoMode(QLineEdit.EchoMode.Password)
        self.password.setPlaceholderText(
            SEED_ADMIN_PASSWORD if self._seeded else "Your password"
        )
        form.addRow(QLabel("Password"), self.password)

        layout.addLayout(form)

        btn_row = QHBoxLayout()
        cancel = QPushButton("Cancel"); cancel.setFixedHeight(34)
        cancel.clicked.connect(self.reject)
        btn_row.addWidget(cancel)

        signin = QPushButton("Sign in"); signin.setFixedHeight(34)
        signin.setObjectName("btn_primary")
        signin.clicked.connect(self._try_login)
        btn_row.addWidget(signin)
        layout.addLayout(btn_row)

        # Enter on either field submits.
        self.username.returnPressed.connect(self._try_login)
        self.password.returnPressed.connect(self._try_login)

        # Pre-fill seeded creds so the very first sign-in is one-click.
        if self._seeded:
            self.username.setText(SEED_ADMIN_USERNAME)
            self.password.setText(SEED_ADMIN_PASSWORD)
            self.password.setFocus()
        else:
            self.username.setFocus()

    def _try_login(self) -> None:
        u = self.username.text().strip()
        p = self.password.text()
        if not u or not p:
            QMessageBox.warning(self, "Sign in",
                                "Username and password are both required.")
            return
        session = self.users.authenticate(u, p)
        if session is None:
            QMessageBox.warning(
                self, "Sign in",
                "Username or password is incorrect, or the account is "
                "disabled."
            )
            self.password.clear()
            self.password.setFocus()
            return
        self.session = session
        self.accept()
