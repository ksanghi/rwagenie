# RWAGenie

Resident Welfare Association management front, built on the
[AccGenie](https://github.com/ksanghi/aiccounting) accounting engine.

This is a **separate Windows application** with its own brand, sidebar,
pages, and installer. It is **not** bundled into AccGenie; AccGenie
continues to ship as a standalone accounting app.

## Architecture

```
RWAGenie shell (this repo)              AccGenie engine (sibling repo)
─────────────────────────                ──────────────────────────────
app/main.py    ─ launcher                core/models.py     ─ DB schema
app/main_window.py ─ extends             core/account_tree.py
                  AG's MainWindow        core/voucher_engine.py
app/pages/                               core/reports_engine.py
  flats_page.py                          core/bank_reconciliation.py
  members_page.py                        core/license_manager.py
  notice_board_page.py    ── imports ──► ui/main_window.py (base shell)
  complaints_page.py                     ui/theme.py
  …                                      …
app/services/                            (re-used through PYTHONPATH;
  flats, owners, billing, …               AG is cloned as a sibling
app/models.py                             directory, not vendored)
  rwa_* tables
```

RWAGenie inherits from AccGenie's `MainWindow` at runtime — every
accounting page (Voucher form, Day Book, Reports, GST returns, Bank
Reconciliation) is available unchanged inside RWAGenie. The RWA-specific
pages get added on top.

## Local development

Clone AccGenie and RWAGenie as **siblings**:

```
C:\Users\ksang\eclipse-workspace\
├── Aiccounting\    ← AccGenie repo
└── rwagenie\       ← this repo
```

`main.py` adds `../Aiccounting` to `sys.path` at startup so all
`from core.*` and `from ui.*` imports resolve to the AG engine.

### Run from source

```
cd C:\Users\ksang\eclipse-workspace\rwagenie
python main.py
```

Requires AccGenie's runtime deps to be installed in the active Python
(`pip install -r ..\Aiccounting\requirements.txt`).

## Build the installer

`build\build.bat` runs Nuitka against `main.py` with the sibling AG
folder included. Output: `build\dist\RWAGenie-Setup-X.Y.Z.exe`. The
installer is self-contained — the customer machine does **not** need
AccGenie pre-installed.

## License model

License keys are issued by the same AccGenie license server with
`product='rwagenie'`. The server merges AG-tier features + RWA-tier
features and returns them to the client on validate. See
`docs/architecture.md` for details.

## Status

v0.1.0 in active development.
- ✅ Flats master + companion ledgers
- ✅ Member directory + flat assignments
- 🔴 Notice board, complaints, broadcasts, polls, visitor pass
- 🔴 Auto-billing, late fees, facilities booking, asset register (STANDARD+)
- 🔴 WhatsApp invoices, document storage, vendor mgmt (PRO+)
