"""
Broadcast settings dialog — SMTP + SMS credentials per society.

Reachable from the Broadcasts page header ("⚙ Settings"). Owns the
persistence of all delivery-related secrets and the "Send test
email / Send test SMS" sanity-check buttons.

Secrets are stored in rwa_settings (per-society kv); see
app/services/settings.py for the canonical key names.
"""
from __future__ import annotations

from PySide6.QtCore    import Qt
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QFormLayout, QTabWidget,
    QLineEdit, QSpinBox, QCheckBox, QLabel, QPushButton, QMessageBox,
    QWidget, QFrame,
)

from app.theme    import THEME
from app.services.settings        import SettingsService
from app.services.broadcast_send  import BroadcastSendService


class BroadcastSettingsDialog(QDialog):
    """Two-tab dialog: Email (SMTP) and SMS (Fast2SMS). Each tab has
    its own "Save" + "Send test" so the admin can iterate on one
    channel without touching the other."""

    def __init__(self, db, company_id: int, parent=None):
        super().__init__(parent)
        self.db = db
        self.company_id = company_id
        self.settings   = SettingsService(db, company_id)
        self.sender_svc = BroadcastSendService(db, company_id)

        self.setWindowTitle("Broadcast — Email & SMS settings")
        self.setMinimumWidth(560)
        self.setModal(True)

        root = QVBoxLayout(self)
        root.setContentsMargins(18, 18, 18, 18)
        root.setSpacing(10)

        title = QLabel("⚙ Broadcast settings")
        title.setStyleSheet(
            f"font-size:15px; font-weight:bold; color:{THEME['accent']};"
        )
        root.addWidget(title)

        hint = QLabel(
            "Per-society credentials. Stored on this machine only — "
            "they don't sync to any cloud yet. Each tab can be saved "
            "and tested independently."
        )
        hint.setWordWrap(True)
        hint.setStyleSheet(
            f"color:{THEME['text_secondary']}; font-size:11px;"
        )
        root.addWidget(hint)

        self.tabs = QTabWidget()
        self.tabs.addTab(self._build_email_tab(), "Email (SMTP)")
        self.tabs.addTab(self._build_sms_tab(),   "SMS (Fast2SMS)")
        root.addWidget(self.tabs, 1)

        close = QPushButton("Close")
        close.clicked.connect(self.accept)
        close_row = QHBoxLayout()
        close_row.addStretch()
        close_row.addWidget(close)
        root.addLayout(close_row)

    # ── Email tab ──────────────────────────────────────────────────────

    def _build_email_tab(self) -> QWidget:
        w = QWidget(); v = QVBoxLayout(w); v.setSpacing(8)

        form = QFormLayout(); form.setSpacing(8)
        cfg = self.settings.smtp_config()

        self.smtp_host = QLineEdit(cfg["host"]); self.smtp_host.setFixedHeight(30)
        self.smtp_host.setPlaceholderText("smtp.gmail.com")
        form.addRow(QLabel("Host"), self.smtp_host)

        self.smtp_port = QSpinBox(); self.smtp_port.setFixedHeight(30)
        self.smtp_port.setRange(1, 65535); self.smtp_port.setValue(cfg["port"] or 465)
        form.addRow(QLabel("Port"), self.smtp_port)

        self.smtp_ssl = QCheckBox("Use SSL (port 465). Uncheck for STARTTLS (port 587).")
        self.smtp_ssl.setChecked(cfg["use_ssl"])
        form.addRow(QLabel(""), self.smtp_ssl)

        self.smtp_user = QLineEdit(cfg["user"]); self.smtp_user.setFixedHeight(30)
        self.smtp_user.setPlaceholderText("yourname@gmail.com")
        form.addRow(QLabel("Username"), self.smtp_user)

        self.smtp_password = QLineEdit(cfg["password"]); self.smtp_password.setFixedHeight(30)
        self.smtp_password.setEchoMode(QLineEdit.EchoMode.Password)
        self.smtp_password.setPlaceholderText("App Password — not your normal login")
        form.addRow(QLabel("Password"), self.smtp_password)

        self.smtp_from_name = QLineEdit(cfg["from_name"]); self.smtp_from_name.setFixedHeight(30)
        self.smtp_from_name.setPlaceholderText("Sunrise Apartments RWA")
        form.addRow(QLabel("From name"), self.smtp_from_name)

        self.smtp_from_email = QLineEdit(cfg["from_email"]); self.smtp_from_email.setFixedHeight(30)
        self.smtp_from_email.setPlaceholderText("(defaults to Username)")
        form.addRow(QLabel("From email"), self.smtp_from_email)

        v.addLayout(form)

        gmail = QLabel(
            "📌 <b>Gmail users:</b> generate an App Password at "
            "<a href='https://myaccount.google.com/apppasswords'>"
            "myaccount.google.com/apppasswords</a> (requires 2FA enabled). "
            "Your normal Gmail password will NOT work."
        )
        gmail.setOpenExternalLinks(True); gmail.setWordWrap(True)
        gmail.setStyleSheet(
            f"color:{THEME['text_secondary']}; font-size:10px;"
            f" background:{THEME.get('bg_hover','#334155')};"
            f" padding:8px; border-radius:6px;"
        )
        v.addWidget(gmail)

        # Action row: Save + Send test
        row = QHBoxLayout()
        save = QPushButton("Save"); save.setObjectName("btn_primary")
        save.setFixedHeight(32); save.clicked.connect(self._save_smtp)
        row.addWidget(save)

        self.smtp_test_to = QLineEdit(); self.smtp_test_to.setFixedHeight(32)
        self.smtp_test_to.setPlaceholderText("test recipient email")
        row.addWidget(self.smtp_test_to, 2)

        test = QPushButton("Send test email"); test.setFixedHeight(32)
        test.clicked.connect(self._test_smtp)
        row.addWidget(test)
        v.addLayout(row)

        v.addStretch(1)
        return w

    def _save_smtp(self) -> None:
        for ed in (self.smtp_host, self.smtp_user, self.smtp_password,
                   self.smtp_from_name, self.smtp_from_email):
            ed.clearFocus()
        self.settings.set_many({
            "smtp.host":       self.smtp_host.text().strip(),
            "smtp.port":       self.smtp_port.value(),
            "smtp.use_ssl":    "true" if self.smtp_ssl.isChecked() else "false",
            "smtp.user":       self.smtp_user.text().strip(),
            "smtp.password":   self.smtp_password.text(),
            "smtp.from_name":  self.smtp_from_name.text().strip(),
            "smtp.from_email": self.smtp_from_email.text().strip(),
        })
        QMessageBox.information(self, "Saved", "SMTP settings saved.")

    def _test_smtp(self) -> None:
        to = self.smtp_test_to.text().strip()
        if not to:
            QMessageBox.warning(self, "Test email",
                                "Enter a recipient email first.")
            return
        # Save before test so the user doesn't have to remember to.
        self._save_smtp_quiet()
        try:
            self.sender_svc.send_test_email(to)
        except Exception as e:
            QMessageBox.critical(self, "Test failed",
                                 f"SMTP test failed:\n\n{e}")
            return
        QMessageBox.information(self, "Test sent",
                                f"Test email sent to {to}.")

    def _save_smtp_quiet(self) -> None:
        self.settings.set_many({
            "smtp.host":       self.smtp_host.text().strip(),
            "smtp.port":       self.smtp_port.value(),
            "smtp.use_ssl":    "true" if self.smtp_ssl.isChecked() else "false",
            "smtp.user":       self.smtp_user.text().strip(),
            "smtp.password":   self.smtp_password.text(),
            "smtp.from_name":  self.smtp_from_name.text().strip(),
            "smtp.from_email": self.smtp_from_email.text().strip(),
        })

    # ── SMS tab ────────────────────────────────────────────────────────

    def _build_sms_tab(self) -> QWidget:
        w = QWidget(); v = QVBoxLayout(w); v.setSpacing(8)

        form = QFormLayout(); form.setSpacing(8)
        cfg = self.settings.sms_config()

        provider_row = QLabel("Provider: <b>Fast2SMS</b> (only supported in v0.1.2)")
        provider_row.setStyleSheet(f"color:{THEME['text_secondary']}; font-size:11px;")
        form.addRow(QLabel(""), provider_row)

        self.sms_api_key = QLineEdit(cfg["api_key"]); self.sms_api_key.setFixedHeight(30)
        self.sms_api_key.setEchoMode(QLineEdit.EchoMode.Password)
        self.sms_api_key.setPlaceholderText("Dev API key from fast2sms.com dashboard")
        form.addRow(QLabel("API key"), self.sms_api_key)

        self.sms_sender_id = QLineEdit(cfg["sender_id"]); self.sms_sender_id.setFixedHeight(30)
        self.sms_sender_id.setMaxLength(6)
        self.sms_sender_id.setPlaceholderText("6-char DLT sender (transactional only)")
        form.addRow(QLabel("Sender ID"), self.sms_sender_id)

        v.addLayout(form)

        hint = QLabel(
            "📌 <b>Indian SMS rules:</b> for transactional SMS you need "
            "DLT registration + an approved template + a 6-char sender ID. "
            "For ad-hoc / informational broadcasts, leave Sender ID blank "
            "and Fast2SMS uses a default route. "
            "Sign up: <a href='https://www.fast2sms.com'>fast2sms.com</a>."
        )
        hint.setOpenExternalLinks(True); hint.setWordWrap(True)
        hint.setStyleSheet(
            f"color:{THEME['text_secondary']}; font-size:10px;"
            f" background:{THEME.get('bg_hover','#334155')};"
            f" padding:8px; border-radius:6px;"
        )
        v.addWidget(hint)

        row = QHBoxLayout()
        save = QPushButton("Save"); save.setObjectName("btn_primary")
        save.setFixedHeight(32); save.clicked.connect(self._save_sms)
        row.addWidget(save)

        self.sms_test_to = QLineEdit(); self.sms_test_to.setFixedHeight(32)
        self.sms_test_to.setPlaceholderText("test recipient number (10 digits)")
        row.addWidget(self.sms_test_to, 2)

        test = QPushButton("Send test SMS"); test.setFixedHeight(32)
        test.clicked.connect(self._test_sms)
        row.addWidget(test)
        v.addLayout(row)

        v.addStretch(1)
        return w

    def _save_sms(self) -> None:
        for ed in (self.sms_api_key, self.sms_sender_id):
            ed.clearFocus()
        self.settings.set_many({
            "sms.provider":  "fast2sms",
            "sms.api_key":   self.sms_api_key.text().strip(),
            "sms.sender_id": self.sms_sender_id.text().strip().upper(),
            "sms.route":     "q",
        })
        QMessageBox.information(self, "Saved", "SMS settings saved.")

    def _test_sms(self) -> None:
        to = self.sms_test_to.text().strip()
        if not to:
            QMessageBox.warning(self, "Test SMS",
                                "Enter a 10-digit mobile number first.")
            return
        self.settings.set_many({
            "sms.provider":  "fast2sms",
            "sms.api_key":   self.sms_api_key.text().strip(),
            "sms.sender_id": self.sms_sender_id.text().strip().upper(),
        })
        try:
            self.sender_svc.send_test_sms(to)
        except Exception as e:
            QMessageBox.critical(self, "Test failed",
                                 f"SMS test failed:\n\n{e}")
            return
        QMessageBox.information(self, "Test sent",
                                f"Test SMS sent to {to}.")
