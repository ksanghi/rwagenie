"""
RWAGenie-specific tables.

These are *additive* on top of the AccGenie company-DB schema. AG's
`core/models.py` SCHEMA is applied first (vouchers, ledgers, etc.);
then `apply_rwa_schema(conn)` runs the CREATE TABLE IF NOT EXISTS
statements below.

Single DB file per company — RWAGenie shares the same .db file as
AccGenie would, just with extra tables. This means a customer's
accounting and RWA data live together; no cross-database sync.

Schema:
  rwa_flats        ─ one row per flat/unit. Auto-creates a Sundry
                     Debtor ledger named "Flat <no>" so maintenance
                     billing can post against it.
  rwa_owners       ─ one row per person; multi-flat through the link
                     table below.
  rwa_flat_owners  ─ many-to-many between flats and owners. Supports
                     joint ownership, tenants, family members.

Future tables (v0.1+): rwa_notices, rwa_complaints, rwa_polls,
rwa_visitor_passes, rwa_bills, rwa_facilities_bookings, …
"""
from __future__ import annotations


_SCHEMA = """
CREATE TABLE IF NOT EXISTS rwa_flats (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    company_id      INTEGER NOT NULL REFERENCES companies(id),
    flat_no         TEXT NOT NULL,                 -- "101", "A-203", "T2-805"
    block           TEXT,
    tower           TEXT,
    floor           TEXT,
    flat_type       TEXT,                          -- 1BHK / 2BHK / 3BHK / 4BHK / PENTHOUSE / STUDIO / SHOP
    area_sqft       REAL,                          -- carpet area
    built_up_area_sqft REAL,                       -- built-up area (often used for billing)
    parking_count   INTEGER DEFAULT 0,             -- number of allotted parking slots
    storage_no      TEXT,                          -- locker / storage room identifier
    ownership_type  TEXT DEFAULT 'OWNED',          -- OWNED / RENTED / VACANT (legacy; see occupation_status)
    occupation_status TEXT DEFAULT 'OWNER_OCCUPIED', -- OWNER_OCCUPIED / RENTED / VACANT
    -- Triangle pointers: the legal owner and the current resident-tenant
    -- (if any). NULL tenant = owner-occupied or vacant. bill_payer says
    -- which of these two the maintenance bill chases.
    primary_owner_id  INTEGER REFERENCES rwa_owners(id),
    primary_tenant_id INTEGER REFERENCES rwa_owners(id),
    bill_payer        TEXT DEFAULT 'OWNER',        -- 'OWNER' or 'TENANT'
    sale_deed_date    TEXT,                        -- YYYY-MM-DD
    possession_date   TEXT,                        -- YYYY-MM-DD
    ledger_id       INTEGER REFERENCES ledgers(id),
    move_in_date    TEXT,                          -- YYYY-MM-DD (legacy; see possession_date)
    notes           TEXT,
    active          INTEGER NOT NULL DEFAULT 1,
    created_at      TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(company_id, flat_no)
);

CREATE TABLE IF NOT EXISTS rwa_owners (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    company_id      INTEGER NOT NULL REFERENCES companies(id),
    name            TEXT NOT NULL,
    primary_phone   TEXT,
    alternate_phone TEXT,
    email           TEXT,
    -- KYC
    pan             TEXT,                          -- separate field even though kyc_id_type can be PAN; TDS code needs to read it directly
    aadhaar_last4   TEXT,                          -- last 4 digits only (compliance — don't store full)
    kyc_id_type     TEXT,                          -- AADHAR / PAN / VOTER / DL / PASSPORT (legacy; pan/aadhaar_last4 are the structured fields)
    kyc_id_number   TEXT,
    photo_path      TEXT,
    correspondence_address TEXT,                   -- may differ from flat (absentee owners)
    is_resident     INTEGER NOT NULL DEFAULT 1,    -- 1 = lives in their own flat; 0 = absentee
    emergency_name  TEXT,
    emergency_phone TEXT,
    -- Payment preferences (used when this owner is the bill_payer)
    preferred_payment_mode   TEXT,                 -- UPI / NACH / TRANSFER / CHEQUE / CASH
    upi_id                   TEXT,                 -- e.g. krishan@oksbi
    bank_account_no          TEXT,
    bank_ifsc                TEXT,
    bank_account_holder_name TEXT,                 -- may differ from owner (joint a/c, HUF)
    nach_mandate_ref         TEXT,                 -- UMRN once auto-debit registered
    notes           TEXT,
    active          INTEGER NOT NULL DEFAULT 1,
    created_at      TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS rwa_flat_owners (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    flat_id         INTEGER NOT NULL REFERENCES rwa_flats(id) ON DELETE CASCADE,
    owner_id        INTEGER NOT NULL REFERENCES rwa_owners(id) ON DELETE CASCADE,
    role            TEXT NOT NULL DEFAULT 'OWNER', -- OWNER / TENANT / FAMILY
    is_primary      INTEGER NOT NULL DEFAULT 0,
    since_date      TEXT,
    -- Tenancy fields — only meaningful when role='TENANT'.
    tenancy_from              TEXT,                -- YYYY-MM-DD
    tenancy_to                TEXT,                -- YYYY-MM-DD
    police_verification_ref   TEXT,                -- legal record; required in most Indian cities
    police_verification_date  TEXT,
    monthly_rent              REAL,                -- informational
    security_deposit          REAL,
    lease_doc_path            TEXT,                -- relative path under data/<company>/leases/
    UNIQUE(flat_id, owner_id, role)
);

CREATE INDEX IF NOT EXISTS idx_rwa_flats_company  ON rwa_flats(company_id, active);
CREATE INDEX IF NOT EXISTS idx_rwa_owners_company ON rwa_owners(company_id, active);
CREATE INDEX IF NOT EXISTS idx_rwa_fo_flat        ON rwa_flat_owners(flat_id);
CREATE INDEX IF NOT EXISTS idx_rwa_fo_owner       ON rwa_flat_owners(owner_id);

-- ── Free-tier RWA features (schemas only; CRUD pages TBD in v0.1) ─────────

-- Notice board: society-wide announcements visible to all members.
CREATE TABLE IF NOT EXISTS rwa_notices (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    company_id      INTEGER NOT NULL REFERENCES companies(id),
    title           TEXT NOT NULL,
    body            TEXT NOT NULL DEFAULT '',
    posted_by       TEXT,                          -- name as entered, no FK
    pinned          INTEGER NOT NULL DEFAULT 0,
    expires_on      TEXT,                          -- auto-hide after this date
    created_at      TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_rwa_notices_company ON rwa_notices(company_id, pinned, created_at);

-- Complaints: maintenance / civic issues raised by residents, tracked
-- to resolution.
CREATE TABLE IF NOT EXISTS rwa_complaints (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    company_id      INTEGER NOT NULL REFERENCES companies(id),
    flat_id         INTEGER REFERENCES rwa_flats(id),
    raised_by_owner INTEGER REFERENCES rwa_owners(id),
    category        TEXT,                          -- PLUMBING / ELECTRICAL / NOISE / SECURITY / OTHER
    title           TEXT NOT NULL,
    description     TEXT,
    priority        TEXT DEFAULT 'NORMAL',         -- LOW / NORMAL / HIGH / URGENT
    status          TEXT NOT NULL DEFAULT 'OPEN',  -- OPEN / IN_PROGRESS / RESOLVED / CLOSED
    assigned_to     TEXT,
    resolution_notes TEXT,
    raised_at       TEXT NOT NULL DEFAULT (datetime('now')),
    resolved_at     TEXT
);
CREATE INDEX IF NOT EXISTS idx_rwa_complaints_company ON rwa_complaints(company_id, status, raised_at);

-- Broadcasts: targeted messages (SMS/email/WhatsApp later) to a flat
-- set. For v0.1 we just persist the message and recipient list; delivery
-- channel comes later.
CREATE TABLE IF NOT EXISTS rwa_broadcasts (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    company_id      INTEGER NOT NULL REFERENCES companies(id),
    subject         TEXT NOT NULL,
    body            TEXT NOT NULL DEFAULT '',
    channel         TEXT DEFAULT 'NONE',           -- NONE / EMAIL / SMS / WHATSAPP (delivery TBD)
    audience        TEXT DEFAULT 'ALL',            -- ALL / OWNERS / TENANTS / OUTSTANDING / SELECTED
    selected_flats  TEXT,                          -- CSV of flat_ids when audience=SELECTED
    sent_at         TEXT,
    sent_count      INTEGER DEFAULT 0,
    created_at      TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Polls: society votes (AGM resolutions, amenity choices, etc.).
CREATE TABLE IF NOT EXISTS rwa_polls (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    company_id      INTEGER NOT NULL REFERENCES companies(id),
    title           TEXT NOT NULL,
    description     TEXT,
    options_json    TEXT NOT NULL,                 -- JSON list of option strings
    opens_at        TEXT,
    closes_at       TEXT,
    one_vote_per    TEXT DEFAULT 'FLAT',           -- FLAT / OWNER
    status          TEXT NOT NULL DEFAULT 'DRAFT', -- DRAFT / OPEN / CLOSED / ARCHIVED
    created_at      TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS rwa_poll_votes (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    poll_id         INTEGER NOT NULL REFERENCES rwa_polls(id) ON DELETE CASCADE,
    flat_id         INTEGER REFERENCES rwa_flats(id),
    owner_id        INTEGER REFERENCES rwa_owners(id),
    option_index    INTEGER NOT NULL,
    voted_at        TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(poll_id, flat_id, owner_id)
);

-- Visitor passes: gate-issued or pre-authorised entry passes.
CREATE TABLE IF NOT EXISTS rwa_visitor_passes (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    company_id      INTEGER NOT NULL REFERENCES companies(id),
    flat_id         INTEGER REFERENCES rwa_flats(id),
    visitor_name    TEXT NOT NULL,
    visitor_phone   TEXT,
    vehicle_no      TEXT,
    purpose         TEXT,                          -- GUEST / DELIVERY / SERVICE / OTHER
    expected_at     TEXT,
    valid_until     TEXT,
    entry_time      TEXT,
    exit_time       TEXT,
    pass_code       TEXT,                          -- short alphanumeric for the gate
    issued_by       TEXT,
    created_at      TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_rwa_visitor_passes_company ON rwa_visitor_passes(company_id, entry_time);
"""


# Additive migrations: columns added AFTER a table's CREATE statement
# was first applied to an existing DB. SQLite has no
# `ALTER TABLE ADD COLUMN IF NOT EXISTS`, so we check PRAGMA table_info
# and ALTER only when missing. Mirrors AG's _ADDITIVE_COLUMNS pattern
# (core/models.py).
#
# Add an entry here when introducing a new column to any rwa_* table
# AFTER its initial CREATE has shipped. Then update the CREATE statement
# above too — fresh DBs get the column directly, existing DBs get it
# via ALTER on next launch.

_RWA_ADDITIVE_COLUMNS: list[tuple[str, str, str]] = [
    # rwa_flats — Tier 1 + Tier 2 additions (post-v0.1-initial)
    ("rwa_flats",       "flat_type",                 "TEXT"),
    ("rwa_flats",       "built_up_area_sqft",        "REAL"),
    ("rwa_flats",       "parking_count",             "INTEGER DEFAULT 0"),
    ("rwa_flats",       "storage_no",                "TEXT"),
    ("rwa_flats",       "occupation_status",         "TEXT DEFAULT 'OWNER_OCCUPIED'"),
    ("rwa_flats",       "primary_owner_id",          "INTEGER REFERENCES rwa_owners(id)"),
    ("rwa_flats",       "primary_tenant_id",         "INTEGER REFERENCES rwa_owners(id)"),
    ("rwa_flats",       "bill_payer",                "TEXT DEFAULT 'OWNER'"),
    ("rwa_flats",       "sale_deed_date",            "TEXT"),
    ("rwa_flats",       "possession_date",           "TEXT"),
    # rwa_owners — payment + KYC + residency
    ("rwa_owners",      "pan",                       "TEXT"),
    ("rwa_owners",      "aadhaar_last4",             "TEXT"),
    ("rwa_owners",      "correspondence_address",    "TEXT"),
    ("rwa_owners",      "is_resident",               "INTEGER DEFAULT 1"),
    ("rwa_owners",      "preferred_payment_mode",    "TEXT"),
    ("rwa_owners",      "upi_id",                    "TEXT"),
    ("rwa_owners",      "bank_account_no",           "TEXT"),
    ("rwa_owners",      "bank_ifsc",                 "TEXT"),
    ("rwa_owners",      "bank_account_holder_name",  "TEXT"),
    ("rwa_owners",      "nach_mandate_ref",          "TEXT"),
    # rwa_flat_owners — tenancy details
    ("rwa_flat_owners", "tenancy_from",              "TEXT"),
    ("rwa_flat_owners", "tenancy_to",                "TEXT"),
    ("rwa_flat_owners", "police_verification_ref",   "TEXT"),
    ("rwa_flat_owners", "police_verification_date",  "TEXT"),
    ("rwa_flat_owners", "monthly_rent",              "REAL"),
    ("rwa_flat_owners", "security_deposit",          "REAL"),
    ("rwa_flat_owners", "lease_doc_path",            "TEXT"),
]


def _apply_additive_columns(db) -> None:
    conn = db.connect()
    for table, col, ddl in _RWA_ADDITIVE_COLUMNS:
        existing = {
            row["name"] for row in conn.execute(f"PRAGMA table_info({table})")
        }
        if col not in existing:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} {ddl}")
    db.commit()


def apply_rwa_schema(db) -> None:
    """Run the RWA schema DDL against an AG `core.models.Database`
    instance.

    1. CREATE TABLE IF NOT EXISTS for every table — idempotent, gives
       fresh DBs the full current schema in one shot.
    2. _apply_additive_columns() runs ALTER TABLE ADD COLUMN for every
       column listed in _RWA_ADDITIVE_COLUMNS that isn't already on the
       table — picks up existing DBs that pre-date a column.

    Safe to call on every RWAGenie launch.
    """
    conn = db.connect()
    conn.executescript(_SCHEMA)
    db.commit()
    _apply_additive_columns(db)
