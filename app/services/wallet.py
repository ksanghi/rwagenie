"""
Desktop client for the AccGenie license-server's SMS wallet.

Mirrors `rwagenie-web/app/wallet.py` (the web-side client) — same
endpoints, same semantics. Every SMS send from the desktop
(`broadcast_send.py`'s SMS path) must call `debit()` BEFORE actually
dispatching via Fast2SMS. If the wallet is empty or the license is
demo / not yet activated, the debit raises and the send is refused.

Why this lives here instead of in AG's `core/` — wallet usage is
RWAGenie-specific; AG itself doesn't broadcast SMS. Keeps the
dependency direction RWAGenie → AG (engine) → license-server, never
the other way.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

import requests

from core.license_manager import LicenseManager, SERVER_URL, DEV_KEY


logger = logging.getLogger(__name__)

# Per-SMS price in paise. Mirrors rwagenie-web/app/config.py:sms_price_paise.
# Both sides MUST charge the same — keep these in sync if pricing changes.
SMS_PRICE_PAISE = 50          # ₹0.50 per SMS


# ── Errors ──────────────────────────────────────────────────────────────

class WalletError(RuntimeError):
    """Base wallet error."""


class WalletUnconfigured(WalletError):
    """No license key on this install — can't debit."""


class InsufficientBalance(WalletError):
    """Wallet balance below the requested debit."""


# ── Client ──────────────────────────────────────────────────────────────

@dataclass
class DebitResult:
    balance_after_paise: int
    txn_id: int


def _server_base() -> str:
    # SERVER_URL is `https://license.accgenie.in/api/v1`. Wallet endpoints
    # already live under /api/v1/wallet/* so we use SERVER_URL directly.
    return SERVER_URL.rstrip("/")


def _resolve_license_key() -> str:
    """Pull the active license key from the in-memory LicenseManager.
    DEV_KEY ('ACCG-DEV-FULL') licenses can't debit — they aren't real
    paying customers and the server would reject them anyway."""
    lic_key = (LicenseManager().license_key or "").strip()
    if not lic_key or lic_key == DEV_KEY or lic_key == "DEMO":
        raise WalletUnconfigured(
            "This install isn't activated with a paid license. "
            "Activate a license before sending SMS."
        )
    return lic_key


def get_balance() -> int:
    """Return current balance in paise for this install's active license.
    Raises WalletError on any failure."""
    key = _resolve_license_key()
    try:
        resp = requests.get(
            f"{_server_base()}/wallet/balance",
            params={"license_key": key}, timeout=10,
        )
    except requests.RequestException as e:
        raise WalletError(f"License-server unreachable: {e}") from e
    try:
        j = resp.json()
    except ValueError:
        raise WalletError(f"License-server non-JSON: {resp.text[:200]}")
    if not j.get("ok"):
        raise WalletError(j.get("error") or f"License-server {resp.status_code}")
    return int(j["balance_paise"])


def debit(*, amount_paise: int = SMS_PRICE_PAISE,
          kind: str = "sms_broadcast",
          recipient_phone: str = "",
          ref: str = "") -> DebitResult:
    """Debit `amount_paise` from this install's wallet. Raises:
      • WalletUnconfigured — no license key locally
      • InsufficientBalance — server has wallet but not enough credit
      • WalletError — anything else (license revoked, network, server bug)

    The caller MUST treat any exception as "do not send the SMS"."""
    key = _resolve_license_key()
    machine_id = LicenseManager.get_machine_id()
    body = {
        "license_key":     key,
        "machine_id":      machine_id,
        "amount_paise":    int(amount_paise),
        "kind":            kind,
        "recipient_phone": recipient_phone or "",
        "ref":             ref or "",
    }
    try:
        resp = requests.post(
            f"{_server_base()}/wallet/debit", json=body, timeout=15,
        )
    except requests.RequestException as e:
        raise WalletError(f"License-server unreachable: {e}") from e

    if resp.status_code == 422:
        raise WalletError(f"Bad debit payload (caller bug): {resp.text[:200]}")
    try:
        j = resp.json()
    except ValueError:
        raise WalletError(f"License-server non-JSON: {resp.text[:200]}")

    if not j.get("ok"):
        err = j.get("error") or "wallet_error"
        if err == "insufficient_balance":
            raise InsufficientBalance(
                f"SMS wallet has only {j.get('balance_after_paise',0)} paise; "
                f"{amount_paise} paise needed. Top up from the Wallet page."
            )
        raise WalletError(err)

    return DebitResult(
        balance_after_paise=int(j["balance_after_paise"]),
        txn_id=int(j["txn_id"]),
    )


def create_topup_order(*, amount_paise: int,
                       customer_email: str = "",
                       customer_name: str = "") -> dict:
    """Ask the license-server to create a Razorpay order for a wallet
    top-up of `amount_paise`. Returns the dict from the server
    (containing `order_id`, `razorpay_key_id`, etc.) which the UI
    hands to Razorpay Checkout in a browser. Raises WalletError on
    failure."""
    key = _resolve_license_key()
    body = {
        "license_key":    key,
        "amount_paise":   int(amount_paise),
        "customer_email": customer_email or "",
        "customer_name":  customer_name or "",
    }
    try:
        resp = requests.post(
            f"{_server_base()}/wallet/topup/create-order",
            json=body, timeout=15,
        )
    except requests.RequestException as e:
        raise WalletError(f"License-server unreachable: {e}") from e
    try:
        j = resp.json()
    except ValueError:
        raise WalletError(f"License-server non-JSON: {resp.text[:200]}")
    if not j.get("ok"):
        raise WalletError(j.get("error") or "wallet_topup_failed")
    return j
