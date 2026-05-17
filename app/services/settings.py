"""
Per-society key/value settings store.

Used today for SMTP creds + SMS API keys. Anything else that needs to
be configurable per society (default reply-to, late-fee rates, etc.)
can plug in here without a schema change.

Keys used elsewhere in the codebase (string constants — keep this
list updated):

    smtp.host                   str   e.g. "smtp.gmail.com"
    smtp.port                   int   e.g. 465
    smtp.use_ssl                bool  "true"/"false"; True = SMTP_SSL,
                                       False = STARTTLS on plain SMTP
    smtp.user                   str   account that authenticates
    smtp.password               str   Gmail App Password / SMTP password
    smtp.from_name              str   display name on outgoing mail
    smtp.from_email             str   "From:" address (often same as user)

    sms.provider                str   "fast2sms" (only supported provider
                                       in v0.1.2; abstraction left in
                                       place for MSG91 / Twilio later)
    sms.api_key                 str
    sms.sender_id               str   6-char DLT-approved sender (Indian
                                       transactional SMS requirement)
    sms.route                   str   "q" = transactional, "p" = promotional;
                                       defaults to "q"

Values are stored as TEXT. Callers convert as needed via the typed
helpers (`get_int`, `get_bool`).
"""
from __future__ import annotations

from typing import Any, Optional


class SettingsService:
    def __init__(self, db, company_id: int):
        self.db = db
        self.company_id = company_id

    def get(self, key: str, default: Optional[str] = None) -> Optional[str]:
        row = self.db.execute(
            "SELECT value FROM rwa_settings WHERE company_id=? AND key=?",
            (self.company_id, key),
        ).fetchone()
        return row["value"] if row else default

    def get_int(self, key: str, default: int = 0) -> int:
        v = self.get(key)
        try:
            return int(v) if v is not None and v != "" else default
        except (TypeError, ValueError):
            return default

    def get_bool(self, key: str, default: bool = False) -> bool:
        v = self.get(key)
        if v is None:
            return default
        return str(v).strip().lower() in ("1", "true", "yes", "y", "on")

    def set(self, key: str, value: Any) -> None:
        text = "" if value is None else str(value)
        self.db.execute(
            """INSERT INTO rwa_settings (company_id, key, value)
                    VALUES (?,?,?)
               ON CONFLICT(company_id, key) DO UPDATE
                  SET value=excluded.value,
                      updated_at=datetime('now')""",
            (self.company_id, key, text),
        )
        self.db.commit()

    def set_many(self, items: dict[str, Any]) -> None:
        for k, v in items.items():
            self.set(k, v)

    def delete(self, key: str) -> None:
        self.db.execute(
            "DELETE FROM rwa_settings WHERE company_id=? AND key=?",
            (self.company_id, key),
        )
        self.db.commit()

    # ── Convenience bundles ─────────────────────────────────────────────

    def smtp_config(self) -> dict:
        """Returns a dict ready to pass to BroadcastSendService.
        Missing keys come back as empty strings / sensible defaults."""
        return {
            "host":       self.get("smtp.host") or "",
            "port":       self.get_int("smtp.port", 465),
            "use_ssl":    self.get_bool("smtp.use_ssl", True),
            "user":       self.get("smtp.user") or "",
            "password":   self.get("smtp.password") or "",
            "from_name":  self.get("smtp.from_name") or "",
            "from_email": self.get("smtp.from_email") or self.get("smtp.user") or "",
        }

    def sms_config(self) -> dict:
        return {
            "provider":   self.get("sms.provider") or "fast2sms",
            "api_key":    self.get("sms.api_key") or "",
            "sender_id":  self.get("sms.sender_id") or "",
            "route":      self.get("sms.route") or "q",
        }
