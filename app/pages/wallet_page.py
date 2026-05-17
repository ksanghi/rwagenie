"""
Wallet page — shows the society's SMS wallet balance, recent
transactions, and a Top-up button.

The wallet lives on the license-server (one row per License). Every
SMS the desktop or rwagenie-web sends debits it. Admin tops up via
Razorpay; the existing checkout integration handles payment.

This page is intentionally read-mostly: top-up flow opens the
Razorpay checkout in a system browser (we don't ship Razorpay JS
inside Qt). Transaction history is not yet exposed via a list
endpoint on the license-server — for v0.1 we just show the
current balance + a "Refresh" button. Detailed audit will land
when ops needs it.
"""
from __future__ import annotations

import logging
import webbrowser
from typing import Optional

from PySide6.QtCore    import Qt, QThread, QObject, Signal
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QFrame,
    QMessageBox, QDialog, QFormLayout, QSpinBox, QLineEdit,
)

from app.theme    import THEME
from app.services import wallet


logger = logging.getLogger(__name__)


# ── Balance fetch worker (off the Qt thread — license-server call is HTTP) ──

class _BalanceWorker(QObject):
    done = Signal(int, str)        # balance_paise (-1 on error), err_msg

    def run(self):
        try:
            bal = wallet.get_balance()
            self.done.emit(bal, "")
        except wallet.WalletUnconfigured as e:
            self.done.emit(-1, f"unconfigured: {e}")
        except wallet.WalletError as e:
            self.done.emit(-1, str(e))


# ── Top-up dialog ───────────────────────────────────────────────────────

class _TopupDialog(QDialog):
    """Pick an amount → opens Razorpay checkout in the system browser.

    Once payment succeeds, the license-server's webhook credits the
    wallet. The admin returns to the Wallet page and clicks Refresh
    to see the new balance.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Top up SMS wallet")
        self.setMinimumWidth(420)
        self.setModal(True)

        v = QVBoxLayout(self)
        v.setContentsMargins(20, 20, 20, 20); v.setSpacing(10)

        hdr = QLabel("💰 Top up SMS wallet")
        hdr.setStyleSheet(
            f"font-size:14px; font-weight:bold; color:{THEME['accent']};"
        )
        v.addWidget(hdr)

        info = QLabel(
            "At ₹0.50 per SMS, common top-up sizes:\n"
            "  • ₹500 = 1 000 SMS\n"
            "  • ₹1 000 = 2 000 SMS\n"
            "  • ₹2 500 = 5 000 SMS\n\n"
            "Click 'Pay' to open Razorpay in your browser. Once payment "
            "is confirmed, return here and press Refresh."
        )
        info.setWordWrap(True)
        info.setStyleSheet(f"color:{THEME['text_secondary']}; font-size:11px;")
        v.addWidget(info)

        form = QFormLayout(); form.setSpacing(8)
        self.amount_inr = QSpinBox()
        self.amount_inr.setRange(100, 100_000)
        self.amount_inr.setSingleStep(100)
        self.amount_inr.setValue(500)
        self.amount_inr.setSuffix("  INR")
        form.addRow(QLabel("Amount"), self.amount_inr)

        self.email = QLineEdit()
        self.email.setPlaceholderText("(optional — receipt email)")
        form.addRow(QLabel("Email"), self.email)
        v.addLayout(form)

        row = QHBoxLayout(); row.addStretch()
        cancel = QPushButton("Cancel"); cancel.clicked.connect(self.reject)
        pay = QPushButton("Pay"); pay.setObjectName("btn_primary")
        pay.clicked.connect(self._pay)
        row.addWidget(cancel); row.addWidget(pay)
        v.addLayout(row)

    def _pay(self):
        amount_inr = self.amount_inr.value()
        amount_paise = amount_inr * 100
        try:
            order = wallet.create_topup_order(
                amount_paise=amount_paise,
                customer_email=self.email.text().strip() or "",
            )
        except wallet.WalletError as e:
            QMessageBox.critical(
                self, "Top-up failed",
                f"Couldn't create the payment order:\n\n{e}\n\n"
                f"If this persists, contact support@accgenie.in.",
            )
            return

        # The order dict has order_id + razorpay_key_id. For v0.1 we
        # construct a Razorpay-hosted checkout URL using the order_id
        # and let the system browser handle the rest.
        # (Razorpay's preferred flow is JS embed, but Qt-embed of
        # Razorpay JS is a different rabbit hole; the hosted URL works
        # universally.)
        url = (
            f"https://checkout.razorpay.com/v1/checkout/embedded.html"
            f"?order_id={order['order_id']}"
        )
        QMessageBox.information(
            self, "Pay in browser",
            f"Opening Razorpay checkout in your browser.\n\n"
            f"Amount: ₹{amount_inr:,}\n\n"
            f"After successful payment, return here and click "
            f"'Refresh balance'."
        )
        webbrowser.open(url)
        self.accept()


# ── Wallet page ─────────────────────────────────────────────────────────

class WalletPage(QWidget):
    def __init__(self, db, company_id: int, tree, parent=None):
        super().__init__(parent)
        self.db = db
        self.company_id = company_id

        # Hold thread/worker so GC doesn't kill an in-flight balance fetch.
        self._thread: QThread | None = None
        self._worker: _BalanceWorker | None = None

        self._build_ui()
        self.refresh()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 16, 24, 24); layout.setSpacing(12)

        title = QLabel("SMS Wallet")
        title.setObjectName("page_title")
        layout.addWidget(title)

        sub = QLabel(
            "Pre-paid balance for SMS — used for resident login codes "
            "and broadcasts. ₹0.50 per SMS. Top up via UPI or card; "
            "credit applies instantly after payment."
        )
        sub.setObjectName("page_subtitle")
        layout.addWidget(sub)

        # Balance card
        self.balance_card = QFrame()
        self.balance_card.setObjectName("card")
        self.balance_card.setStyleSheet(
            f"QFrame#card {{ background:{THEME.get('bg_hover','#334155')};"
            f" border-radius:8px; padding:16px; }}"
        )
        card_l = QVBoxLayout(self.balance_card)
        card_l.setSpacing(4)
        card_l.setContentsMargins(20, 16, 20, 16)

        self.balance_label = QLabel("Balance: —")
        self.balance_label.setStyleSheet(
            f"font-size:32px; font-weight:bold; color:{THEME['accent']};"
        )
        card_l.addWidget(self.balance_label)

        self.sms_count_label = QLabel("")
        self.sms_count_label.setStyleSheet(
            f"font-size:12px; color:{THEME['text_secondary']};"
        )
        card_l.addWidget(self.sms_count_label)

        self.status_label = QLabel("")
        self.status_label.setStyleSheet(
            f"font-size:11px; color:{THEME['text_secondary']};"
        )
        card_l.addWidget(self.status_label)
        layout.addWidget(self.balance_card)

        # Action row
        bar = QHBoxLayout()
        refresh = QPushButton("⟲ Refresh balance"); refresh.setFixedHeight(34)
        refresh.clicked.connect(self.refresh)
        bar.addWidget(refresh)

        topup = QPushButton("+ Top up"); topup.setObjectName("btn_primary")
        topup.setFixedHeight(34); topup.clicked.connect(self._on_topup)
        bar.addWidget(topup)
        bar.addStretch()
        layout.addLayout(bar)

        # Help / pricing note
        note = QLabel(
            "<b>How it works:</b><br>"
            "• Each SMS (resident OTP login or broadcast message) "
            "costs ₹0.50 from your wallet.<br>"
            "• Top up any amount from ₹100 upwards. Larger top-ups don't "
            "expire — use them over months.<br>"
            "• Web / mobile / accounting features are <b>free</b>. "
            "You only ever pay for SMS."
        )
        note.setWordWrap(True)
        note.setStyleSheet(
            f"color:{THEME['text_secondary']}; font-size:11px;"
            f" background:{THEME.get('bg_hover','#334155')};"
            f" padding:12px; border-radius:6px;"
        )
        layout.addWidget(note)

        layout.addStretch(1)

    def refresh(self) -> None:
        """Kick off an async balance fetch; UI updates when it returns."""
        if self._thread is not None:
            return  # already fetching
        self.balance_label.setText("Balance: …")
        self.sms_count_label.setText("")
        self.status_label.setText("Checking with license-server…")

        self._thread = QThread(self)
        self._worker = _BalanceWorker()
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.done.connect(self._on_balance_done)
        self._worker.done.connect(self._thread.quit)
        self._thread.finished.connect(self._worker.deleteLater)
        self._thread.finished.connect(self._thread.deleteLater)
        self._thread.start()

    def _on_balance_done(self, balance_paise: int, err: str) -> None:
        self._thread = None
        self._worker = None

        if balance_paise < 0:
            self.balance_label.setText("Balance: —")
            self.sms_count_label.setText("")
            self.status_label.setText(f"❌ {err}")
            return

        rupees = balance_paise / 100
        sms_remaining = balance_paise // wallet.SMS_PRICE_PAISE
        self.balance_label.setText(f"₹ {rupees:,.2f}")
        self.sms_count_label.setText(
            f"~{sms_remaining:,} SMS remaining at ₹0.50 each"
        )
        if balance_paise == 0:
            self.status_label.setText(
                "⚠ Wallet is empty — residents can't log in until you top up."
            )
        elif sms_remaining < 100:
            self.status_label.setText(
                "⚠ Low balance. Top up to avoid OTP failures."
            )
        else:
            self.status_label.setText("✓ Balance OK.")

    def _on_topup(self) -> None:
        dlg = _TopupDialog(self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            # Browser was opened. We can't observe the payment outcome
            # from here — admin clicks Refresh after paying.
            pass
