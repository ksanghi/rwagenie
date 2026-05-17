"""
Real broadcast delivery — SMTP for Email, Fast2SMS for SMS.

Provider abstraction is intentionally thin in v0.1.2; one provider per
channel. MSG91 / Twilio / WhatsApp Cloud API can be added behind the
same Sender interface without touching the page or service layer.

Architecture:

    BroadcastsPage  ──►  BroadcastSendService.send(bid)
                                    │
                                    ├─ resolve_recipients()  (SQL on rwa_owners + rwa_flat_owners)
                                    ├─ for each recipient: pick channel sender, dispatch
                                    ├─ log per-recipient result into rwa_broadcast_recipients
                                    └─ stamp sent_at + sent_count on rwa_broadcasts

The page wraps the call in a QThread for sends > 10 recipients (Qt UI
freezes otherwise). This module is pure stdlib / requests; no Qt
imports, so it's importable from tests / CLI too.
"""
from __future__ import annotations

import logging
import smtplib
from dataclasses import dataclass, field
from datetime import datetime
from email.message import EmailMessage
from email.utils import formataddr
from typing import Callable, Iterable, Optional

from app.services.settings import SettingsService

logger = logging.getLogger(__name__)


# ── Data types ──────────────────────────────────────────────────────────

@dataclass
class Recipient:
    owner_id:  int
    flat_id:   Optional[int]
    name:      str
    email:     str
    phone:     str


@dataclass
class SendResult:
    sent:    int = 0
    failed:  int = 0
    skipped: int = 0
    errors:  list[str] = field(default_factory=list)

    @property
    def total(self) -> int:
        return self.sent + self.failed + self.skipped


# ── Senders ─────────────────────────────────────────────────────────────

class SMTPSender:
    """Stateful SMTP connection — kept open across many sends in one
    broadcast so we don't redo TLS+auth per recipient."""

    def __init__(self, cfg: dict):
        self.cfg = cfg
        self._smtp: Optional[smtplib.SMTP] = None

    def open(self) -> None:
        host = self.cfg.get("host") or ""
        port = int(self.cfg.get("port") or 465)
        user = self.cfg.get("user") or ""
        pw   = self.cfg.get("password") or ""
        if not (host and user and pw):
            raise RuntimeError(
                "SMTP not configured — set smtp.host / smtp.user / "
                "smtp.password in Settings."
            )
        if self.cfg.get("use_ssl", True):
            self._smtp = smtplib.SMTP_SSL(host, port, timeout=30)
        else:
            self._smtp = smtplib.SMTP(host, port, timeout=30)
            self._smtp.starttls()
        self._smtp.login(user, pw)

    def close(self) -> None:
        if self._smtp is not None:
            try:
                self._smtp.quit()
            except Exception:
                pass
            self._smtp = None

    def send(self, *, to: str, subject: str, body: str) -> None:
        if self._smtp is None:
            self.open()
        msg = EmailMessage()
        msg.set_content(body)
        msg["Subject"] = subject
        from_addr = self.cfg.get("from_email") or self.cfg.get("user") or ""
        from_name = self.cfg.get("from_name") or ""
        msg["From"] = formataddr((from_name, from_addr)) if from_name else from_addr
        msg["To"]   = to
        assert self._smtp is not None
        self._smtp.send_message(msg)


class Fast2SMSSender:
    """Fast2SMS DLT-route REST sender. One HTTP call per number (we
    don't batch into the comma-separated 'numbers' param — that gives
    one boolean per request, not per-recipient status — so per-recipient
    error reporting is impossible. Send-per-call costs more network but
    yields a usable delivery log)."""

    ENDPOINT = "https://www.fast2sms.com/dev/bulkV2"

    def __init__(self, cfg: dict):
        self.cfg = cfg
        # Lazy import — requests is bundled (AG already uses it for the
        # license server client). Keeps this module importable even if
        # someone runs it in a stripped-down env.
        import requests   # noqa: F401  (deferred so import error is local)

    def send(self, *, to: str, body: str) -> None:
        import requests
        api_key = self.cfg.get("api_key") or ""
        if not api_key:
            raise RuntimeError(
                "Fast2SMS not configured — set sms.api_key in Settings."
            )
        # Normalise: strip +91 / spaces / dashes; Fast2SMS wants
        # 10-digit Indian mobile.
        number = "".join(c for c in to if c.isdigit())
        if number.startswith("91") and len(number) == 12:
            number = number[2:]
        if len(number) != 10:
            raise ValueError(f"Invalid Indian mobile number: {to!r}")

        payload = {
            "message":  body,
            "language": "english",
            "route":    self.cfg.get("route") or "q",
            "numbers":  number,
        }
        sender_id = self.cfg.get("sender_id") or ""
        if sender_id:
            payload["sender_id"] = sender_id

        resp = requests.post(
            self.ENDPOINT,
            headers={"authorization": api_key},
            data=payload,
            timeout=30,
        )
        # Fast2SMS returns {"return": false, "message": "..."} on failure;
        # HTTP 200 + return=false is the common failure shape, so check
        # the body — don't rely on raise_for_status alone.
        try:
            j = resp.json()
        except ValueError:
            resp.raise_for_status()
            raise RuntimeError(f"Fast2SMS: non-JSON response: {resp.text[:200]}")
        if not j.get("return"):
            raise RuntimeError(
                f"Fast2SMS: {j.get('message') or j}"
            )


# ── Main service ────────────────────────────────────────────────────────

class BroadcastSendService:
    """Send a saved broadcast to its resolved audience.

    Owns the per-recipient delivery log + sent_at/sent_count stamping.
    Stateless — instantiated per call from the page.
    """

    def __init__(self, db, company_id: int):
        self.db = db
        self.company_id = company_id
        self.settings = SettingsService(db, company_id)

    # ── Recipient resolution ───────────────────────────────────────────

    def resolve_recipients(self, audience: str,
                            selected_flats: Optional[str] = None,
                            channel: str = "EMAIL") -> list[Recipient]:
        """Return Recipients eligible for the chosen channel. Skips
        owners with no email (EMAIL channel) or no phone (SMS channel)
        — the page logs those as SKIPPED."""
        audience = (audience or "ALL").upper()
        channel  = (channel or "EMAIL").upper()
        cid = self.company_id

        base = """
            SELECT o.id   AS owner_id,
                   f.id   AS flat_id,
                   o.name AS name,
                   COALESCE(o.email,'')         AS email,
                   COALESCE(o.primary_phone,'') AS phone,
                   fo.role
              FROM rwa_owners o
              JOIN rwa_flat_owners fo ON fo.owner_id = o.id
              JOIN rwa_flats f        ON f.id        = fo.flat_id
             WHERE o.company_id=? AND o.active=1 AND f.active=1
        """
        params: list = [cid]

        if audience == "OWNERS":
            base += " AND fo.role='OWNER' "
        elif audience == "TENANTS":
            base += " AND fo.role='TENANT' "
        elif audience == "SELECTED" and selected_flats:
            ids = [int(x) for x in selected_flats.split(",") if x.strip().isdigit()]
            if not ids:
                return []
            placeholders = ",".join("?" * len(ids))
            base += f" AND f.id IN ({placeholders}) "
            params.extend(ids)
        elif audience == "OUTSTANDING":
            # v0.1.2: not wired. Returns the union of primary owners +
            # tenants of flats whose ledger has Dr balance > 0; tied to
            # FlatsService.outstanding_balance_for_flats() when bill
            # generation ships.
            return []

        base += " GROUP BY o.id, f.id "
        rows = self.db.execute(base, params).fetchall()

        out: list[Recipient] = []
        seen: set[int] = set()
        for r in rows:
            oid = r["owner_id"]
            if oid in seen:
                continue
            seen.add(oid)
            out.append(Recipient(
                owner_id=oid, flat_id=r["flat_id"],
                name=r["name"] or "",
                email=r["email"] or "",
                phone=r["phone"] or "",
            ))
        return out

    # ── Send loop ──────────────────────────────────────────────────────

    def send(self, broadcast_id: int,
             on_progress: Optional[Callable[[int, int, str], None]] = None,
             ) -> SendResult:
        """Send one broadcast. Returns a SendResult summary. Writes one
        rwa_broadcast_recipients row per recipient attempt.

        `on_progress(done, total, current_name)` fires after each
        recipient — used by the page to drive a QProgressBar. Keep it
        cheap; it runs in the worker thread.
        """
        bcast = self.db.execute(
            "SELECT * FROM rwa_broadcasts WHERE id=? AND company_id=?",
            (broadcast_id, self.company_id),
        ).fetchone()
        if not bcast:
            raise ValueError(f"Broadcast {broadcast_id} not found.")

        channel = (bcast["channel"] or "NONE").upper()
        if channel == "NONE":
            raise ValueError(
                "Broadcast has channel=None. Set it to Email or SMS "
                "before sending."
            )
        if channel == "WHATSAPP":
            raise ValueError("WhatsApp delivery not implemented in v0.1.2.")

        recipients = self.resolve_recipients(
            bcast["audience"], bcast["selected_flats"], channel,
        )
        result = SendResult()
        total = len(recipients)

        # Pre-clear prior attempts for this broadcast — re-send semantics.
        self.db.execute(
            "DELETE FROM rwa_broadcast_recipients WHERE broadcast_id=?",
            (broadcast_id,),
        )

        sender_smtp: Optional[SMTPSender] = None
        sender_sms:  Optional[Fast2SMSSender] = None
        try:
            if channel == "EMAIL":
                sender_smtp = SMTPSender(self.settings.smtp_config())
                sender_smtp.open()
            elif channel == "SMS":
                sender_sms = Fast2SMSSender(self.settings.sms_config())

            for i, rcpt in enumerate(recipients, start=1):
                addr = rcpt.email if channel == "EMAIL" else rcpt.phone
                status, err = "PENDING", None

                if not addr:
                    status = "SKIPPED"
                    err = f"No {'email' if channel == 'EMAIL' else 'phone'} on record"
                    result.skipped += 1
                else:
                    try:
                        if channel == "EMAIL":
                            assert sender_smtp is not None
                            sender_smtp.send(
                                to=addr,
                                subject=bcast["subject"],
                                body=bcast["body"] or "",
                            )
                        else:  # SMS
                            assert sender_sms is not None
                            sender_sms.send(to=addr, body=bcast["body"] or "")
                        status = "SENT"
                        result.sent += 1
                    except Exception as e:
                        status = "FAILED"
                        err = str(e)[:500]
                        result.failed += 1
                        result.errors.append(f"{rcpt.name}: {err}")
                        logger.warning("Broadcast %d → %s failed: %s",
                                       broadcast_id, rcpt.name, err)

                self.db.execute(
                    """INSERT INTO rwa_broadcast_recipients
                       (broadcast_id, owner_id, flat_id, channel, address,
                        status, error)
                       VALUES (?,?,?,?,?,?,?)""",
                    (broadcast_id, rcpt.owner_id, rcpt.flat_id,
                     channel, addr or "", status, err),
                )
                if on_progress is not None:
                    try:
                        on_progress(i, total, rcpt.name)
                    except Exception:
                        pass

            self.db.execute(
                """UPDATE rwa_broadcasts
                      SET sent_at=?, sent_count=?
                    WHERE id=? AND company_id=?""",
                (datetime.utcnow().isoformat(timespec="seconds"),
                 result.sent, broadcast_id, self.company_id),
            )
            self.db.commit()
        finally:
            if sender_smtp is not None:
                sender_smtp.close()

        return result

    # ── Test helpers ───────────────────────────────────────────────────

    def send_test_email(self, to: str) -> None:
        """Used by the Settings dialog's 'Send test email' button."""
        s = SMTPSender(self.settings.smtp_config())
        try:
            s.open()
            s.send(
                to=to,
                subject="RWAGenie — test email",
                body=("This is a test from RWAGenie. If you can read it, "
                      "SMTP delivery is configured correctly.\n"),
            )
        finally:
            s.close()

    def send_test_sms(self, to: str) -> None:
        """Used by the Settings dialog's 'Send test SMS' button."""
        s = Fast2SMSSender(self.settings.sms_config())
        s.send(to=to, body="RWAGenie test SMS. If you got this, SMS is working.")
