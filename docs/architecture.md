# RWAGenie architecture

## Why a separate repo

RWAGenie is the customer-facing **Resident Welfare Association**
product. It is built on top of the AccGenie accounting engine but
ships as a distinct Windows application with its own brand, sidebar,
installer, version line, and pricing.

A **separate repo** for RWAGenie because:

- Independent version cadence — RWAGenie can iterate on resident-
  facing features without AG version churn, and vice versa.
- Clean blast radius — UI-heavy RWA work doesn't risk regressing
  accounting tests on AG.
- License clarity — `product='rwagenie'` keys are gated server-side
  to the RWAGenie feature bundle.
- Marketing-driven rename is cheap when the codename isn't entangled
  in AG's history.

## Engine reuse — sibling-folder import

RWAGenie does **not** vendor AG code. It does **not** depend on a
published `accgenie-engine` wheel. It imports AG modules directly
through `sys.path` manipulation in `main.py`:

```
eclipse-workspace/
├── Aiccounting/        ← AG repo (engine + AG-only shell)
└── rwagenie/           ← this repo
        main.py         ← adds ../Aiccounting to sys.path
        app/main.py     ← from core.* / from ui.* now resolves
```

When packaged via Nuitka, `--include-package=core --include-package=ui`
bakes both repos into one installer; the customer machine doesn't
need AG installed.

Tradeoffs vs git submodule:
- ✅ No submodule init / update friction.
- ✅ Edit either repo freely; changes are live.
- ❌ No automatic version pinning — RWAGenie depends on "whatever
  AG sibling is checked out". Tag AG commits when cutting RWAGenie
  releases.

## Domain model

RWAGenie shares the **same SQLite company DB** as AG. Per-flat ledgers
sit alongside vouchers and account groups; bank reconciliation,
reports, etc. work unchanged on RWAGenie's data.

RWA tables (`rwa_*`) get created on top of AG's schema via
`app.models.apply_rwa_schema(db)` on every RWAMainWindow init.
Idempotent — `CREATE TABLE IF NOT EXISTS`.

| Table              | What                                          |
|--------------------|-----------------------------------------------|
| `rwa_flats`        | One row per flat/unit. `ledger_id` links to its Sundry Debtor ledger. |
| `rwa_owners`       | One row per person.                          |
| `rwa_flat_owners`  | Many-to-many: joint owners, tenants, family. `is_primary` marks the billing contact. |
| `rwa_notices`      | Society-wide announcements. (CRUD page TBD.) |
| `rwa_complaints`   | Maintenance / civic tickets.                 |
| `rwa_broadcasts`   | Targeted messages (delivery channel TBD).    |
| `rwa_polls` + `rwa_poll_votes` | Society votes.                   |
| `rwa_visitor_passes` | Gate-issued or pre-authorised entry.        |

## UI: subclass AccGenie's MainWindow

`app.main_window.RWAMainWindow` extends `ui.main_window.MainWindow`
from AG. Super's `_build_pages()` mounts every accounting page
(Day Book, Reports, GST, Bank Reco, etc.). After super returns we
add RWA pages on top via `register_page(..., section_above="RWA")`.

Zero accounting-UI duplication. AG bugfixes are inherited
automatically next time the sibling repo is updated.

## License

The same AccGenie license server issues RWAGenie keys with
`product='rwagenie'`. On validate, the server returns the
**merged** feature list — AG's tier features + RWA's tier
features. This matches the operator's spec that an RWAGenie tier
*includes* the matching AG tier's accounting capability.

The desktop client doesn't need to know about the merge; it just
calls `lmgr.has_feature("rwa_auto_billing")` like any other gate.

## What v0.1 ships

- ✅ Flats master + companion ledgers (`rwa_flat_ledger`)
- ✅ Member directory + multi-flat assignment (`rwa_member_directory`)
- 🟡 Schemas for: notice board, complaints, broadcasts, polls,
  visitor pass — sidebar entries show a "Coming soon" placeholder.

## What's deferred to v0.2+

| Feature | Tier   | Notes |
|---|---|---|
| Notice Board CRUD               | FREE     | UI work; schema ready |
| Complaint tracking CRUD         | FREE     | UI work; schema ready |
| Broadcasts (manual)             | FREE     | UI work; schema ready |
| Polls + voting                  | FREE     | UI + simple aggregation |
| Visitor Pass entry              | FREE     | UI; gate-printable PDF |
| **Auto-billing**                | STANDARD | Cron + per-flat templates |
| Late-fee rules                  | STANDARD | Driven by auto-billing |
| Facilities booking              | STANDARD | Calendar + clash detection |
| Asset register + AMC tracking   | STANDARD |  |
| Advanced reports                | STANDARD | Dues outstanding, collection summary |
| WhatsApp invoice reminders      | PRO      | Needs Twilio / WATI / Gupshup. 1–2 mo Meta approval. |
| Document storage                | PRO      | File uploads + categorisation |
| Vendor management               | PRO      | Suppliers, AMCs, AGM voting |
