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
    area_sqft       REAL,
    ownership_type  TEXT DEFAULT 'OWNED',          -- OWNED / RENTED / VACANT
    ledger_id       INTEGER REFERENCES ledgers(id),
    move_in_date    TEXT,                          -- YYYY-MM-DD
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
    kyc_id_type     TEXT,                          -- AADHAR / PAN / VOTER / DL / PASSPORT
    kyc_id_number   TEXT,
    photo_path      TEXT,
    emergency_name  TEXT,
    emergency_phone TEXT,
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


def apply_rwa_schema(db) -> None:
    """Run the RWA schema DDL against an AG `core.models.Database`
    instance. Idempotent — every CREATE is IF NOT EXISTS."""
    conn = db.connect()
    conn.executescript(_SCHEMA)
    db.commit()
