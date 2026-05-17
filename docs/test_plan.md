# RWAGenie test plan

Covers both products:

- **RWAGenie desktop** (`rwagenie/`) — PySide6 admin app, subclasses
  AccGenie's `MainWindow`, ships as a Nuitka-built Windows installer.
- **RWAGenie Web** (`rwagenie-web/`) — FastAPI + SQLAlchemy + Jinja2
  resident portal, deployed to Fly.io.

The two share a sync surface (`app/services/cloud_sync.py` on desktop ↔
`app/routes/sync.py` on web), so a few tests deliberately straddle both
repos.

Scope: v0.1 functionality only — flats, members, notices, complaints,
broadcasts, polls, visitor passes, wallet, audit log, cloud sync,
resident OTP login + dashboard. Auto-billing, late fees, facilities
booking, asset register, WhatsApp invoicing, document storage, vendor
management are deferred to v0.2+ and out of scope here.

---

## 0. Test layers and where they live

| Layer | Tooling | Where |
|---|---|---|
| Unit (services, models) | `unittest` | `rwagenie/tests/`, `rwagenie-web/tests/` |
| Integration (DB + service) | `unittest` + temp SQLite | same |
| API (HTTP) | `pytest` + FastAPI `TestClient` | `rwagenie-web/tests/` |
| Sync contract (cross-repo) | `pytest` + live web TestClient called from desktop service | `rwagenie/tests/test_cloud_sync.py` |
| Manual smoke | checklist in this doc | n/a — runs against `dev.db` + Fly staging |
| Install smoke | manual on a clean Win 11 VM | `rwagenie/build/dist/RWAGenie-Setup-X.Y.Z.exe` |

Existing baseline: `rwagenie/tests/test_imports.py` (sibling-path
bootstrap + idempotent `apply_rwa_schema`). Keep that test passing as a
prerequisite for everything else.

---

## 1. RWAGenie desktop

### 1.1 Schema and models

- **Idempotency** — `apply_rwa_schema(db)` runs twice on a fresh AG
  company DB without errors *(already covered)*.
- **Coexistence** — after `apply_rwa_schema`, AG's own tables
  (`vouchers`, `account_groups`, `companies`) are untouched; insert
  into one and query the other.
- **Companion ledger creation** — creating a flat via `FlatsService`
  creates exactly one Sundry Debtor child ledger with the expected
  name format, and `rwa_flats.ledger_id` points at it. Deleting the
  flat soft-detaches the ledger (does not drop it — outstanding
  vouchers would orphan).
- **Triangle pointers** — `rwa_flats.primary_owner_id`,
  `primary_tenant_id`, `bill_payer` enforce the documented invariants
  (bill_payer ∈ {OWNER, TENANT, EITHER}).

### 1.2 Services (`app/services/*`)

Each service gets a unit test against a temp SQLite. Service-by-service
checks below — call out only what is *not* covered by trivial CRUD
round-trips.

- **`flats.py` / `owners.py`** — owner ↔ flat assignment via
  `rwa_flat_owners`; flipping `is_primary` on one row demotes the
  previous primary in the same flat (single-primary invariant).
- **`notices.py`** — `pinned` notices sort first; `expires_on` filters
  out expired notices from the resident-facing query path used by sync.
- **`complaints.py`** — status transitions OPEN → IN_PROGRESS →
  RESOLVED → CLOSED; `resolved_at` set on RESOLVED only.
- **`broadcasts.py` / `broadcast_send.py`** — dry-run mode renders the
  template per recipient without hitting Fast2SMS; live send debits
  the wallet by the recipient count *before* the API call (test with
  the Fast2SMS client mocked at the `requests` boundary). On HTTP
  failure, the wallet debit must be refunded — that path was the
  reason for an earlier bug, lock it in.
- **`wallet.py`** — `available()`, `debit()`, `credit()`, and
  `record_transaction()` round-trip; concurrent debits do not
  double-spend (run two `debit()` calls on the same session and assert
  exactly one succeeds when balance is short by one).
- **`polls.py`** — `one_vote_per` = FLAT vs RESIDENT changes the
  uniqueness check; closed polls reject new votes.
- **`visitors.py`** — pass-code generator avoids `I`, `O`, `0`, `1`
  (matches the web side, see §2.5); `valid_until` < now blocks gate
  check-in.
- **`audit.py` / `_audit_hooks.py`** — every mutating call on the
  services above lands one row in `rwa_audit_log` with the active
  user, action, table, row pk, and a redacted-but-non-empty diff
  payload. Reads must *not* be logged.
- **`auth.py`** — admin/staff/viewer role gate: viewer cannot call any
  mutating service (assert raises `PermissionError`); admin can; staff
  can call only the subset documented in `app/services/auth.py`.
- **`settings.py`** — kv round-trip; the `cloud.*` keys used by
  `cloud_sync.py` (see §1.4) read and write correctly.

### 1.3 Pages — import + minimal-render smoke

We don't drive PySide6 widgets in unit tests (no QApplication in CI).
But page modules must import cleanly:

- Extend `test_imports.py::test_pages_parse` to import every module in
  `app/pages/*.py` — `flats_page`, `members_page`, `notices_page`,
  `complaints_page`, `broadcasts_page`, `polls_page`,
  `visitor_passes_page`, `wallet_page`, `cloud_sync_page`,
  `users_page`, `audit_log_page`, `login_dialog`,
  `broadcast_settings_dialog`, `_common`, `_audit_hooks`.
- Catches the import-time AG-symbol regressions (a renamed AG class
  breaks RWAGenie at startup, not at click-time).

UI behaviour (button click → service → table refresh) is covered by
the manual smoke checklist in §4.

### 1.4 Cloud sync — desktop side (`app/services/cloud_sync.py`)

- **State helpers** — `is_enabled()`, server URL, sync token,
  society_slug derivation from the .db filename, last_pushed_at /
  last_pulled_at round-trip through `SettingsService`.
- **Bootstrap** — on a fresh desktop, calling
  `cloud_sync.bootstrap()` with a valid license_key hits the license
  server (mock), then `/api/v1/sync/bootstrap` (against a `TestClient`
  for the web app — see §3), receives a `sync_token`, and persists it
  to `rwa_settings`.
- **Push snapshot** — `push()` sends every active flat/resident/
  notice/poll with its desktop_id. Rerunning `push()` with no local
  changes is a no-op on the cloud (idempotent upsert). Soft-deleting
  a flat locally marks it `active=false` on the next push.
- **Pull incremental** — `pull()` sends `since=last_pulled_at` and
  inserts web-originated complaints / poll votes / visitor passes
  into the local rwa_* tables with `origin='web'`. A second pull with
  no new web activity returns zero rows.
- **Round-trip resilience** — a complaint filed on web → pulled to
  desktop → admin updates status to RESOLVED → next push must NOT
  clobber the web `origin` flag and must propagate the status change
  back. (This is the field-level merge that was called out as a known
  v0.1 sharp edge — keep it tested.)
- **Errors** — `NotBootstrapped` raised when no sync_token; network
  failure surfaces as a `CloudSyncError` with `pushed`/`pulled` empty
  and the request error in `errors`.

### 1.5 License gating

- `license_bridge.py` resolves features under `product='rwagenie'`
  with the merge of AG-tier + RWA-tier features (asserted via a
  mocked license-server response).
- Calling a STANDARD-tier service (`auto_billing`, when present) on a
  FREE-tier key raises the expected gate error. v0.1 only has FREE
  features so this test starts as a TODO marker — keep the file
  ready for v0.2.

### 1.6 Build / install

Manual, run before each release tag:

- `cd build && build.bat` produces `dist/RWAGenie-Setup-X.Y.Z.exe`.
- Installer runs on a clean Windows 11 VM with no Python and no
  Aiccounting checkout present.
- First launch:
  - Creates the per-user companies dir, accepts a license key,
    creates a company DB, opens the main window.
  - Sidebar shows both AG sections (Vouchers, Day Book, Reports, GST,
    Bank Reco) and RWA sections (Flats, Members, Notices, Complaints,
    Broadcasts, Polls, Visitor Passes, Wallet, Cloud Sync, Users,
    Audit Log).
- Defender / SmartScreen behaviour matches the `build.bat` note in
  recent commits (no `--product-name` / `--version` flags).

---

## 2. RWAGenie Web

### 2.1 Schema + migrations

- On a fresh `dev.db`, app startup creates every table in `models.py`.
- The seed path (sample society + flat + resident) runs once and is
  idempotent on subsequent startups.
- `UniqueConstraint("society_id", "primary_phone")` on `residents`
  rejects duplicate phone within a society but allows the same phone
  in two different societies.

### 2.2 OTP login (`app/routes/auth.py` + `app/sms.py`)

- **Request OTP** — `POST /auth/request` for a known phone creates
  an `OTP` row whose `code_hash` is the SHA-256 of the live code,
  expires in N minutes, and triggers exactly one `sms.send()` call
  (mock the Fast2SMS HTTP boundary).
- **Verify OTP** — `POST /auth/verify` with the correct code sets a
  session cookie and marks the OTP `used=True`. Wrong code increments
  `attempts`; 3 wrong attempts locks that OTP row.
- **Phone not on roster** — request for an unknown phone returns the
  same generic "OTP sent if phone is registered" message (no oracle).
- **Expiry** — verifying an expired OTP fails even with the correct
  code.
- **Replay** — verifying a `used=True` OTP fails.
- **Rate limit** — N requests within the limit window for the same
  phone return 429 from request N+1.
- **Cookie security** — set-cookie carries `HttpOnly`, `Secure` (when
  not in dev), `SameSite=Lax`, and the documented `Max-Age`.

### 2.3 Resident dashboard (`app/routes/dashboard.py`)

- Logged-in resident sees: own flat number, outstanding_inr from the
  flat row (cloud does NOT recompute — desktop is authoritative), the
  top 5 unexpired notices sorted by pinned-first then created_at desc,
  link to complaints + polls + directory.
- Non-resident (no session) gets 302 to login.
- Resident of society A cannot see society B's notices or flats even
  if they manually craft URLs (society scoping via `deps.py`).

### 2.4 Notices, complaints, polls, directory pages

- **Notices** — full list, pagination if any, pinned/expired filtering
  matches the dashboard behaviour.
- **Complaints — file** — `POST /complaints` creates a row with
  `origin='web'`, `status='OPEN'`, `raised_by_id` = current resident,
  `flat_id` = current resident's primary flat (or null if unassigned).
- **Complaints — track** — resident sees only their own complaints
  unless they're an admin-flagged committee member (out of scope for
  v0.1 — committee role is deferred; assert plain residents see own
  only).
- **Polls — vote** — `POST /polls/{id}/vote` enforces `one_vote_per`
  (FLAT or RESIDENT); replaying the same vote returns 409. Voting on
  a CLOSED poll returns 403. Vote tally updates.
- **Directory** — lists residents in the same society where
  `share_phone=True` or `share_email=True`; residents with both flags
  False appear as name + flat only (no contact info leaks).

### 2.5 Visitor passes

- **Create** — resident creates a pass; `pass_code` is 6+ chars,
  uppercase, drawn from the documented alphabet (no `I`, `O`, `0`,
  `1`). `valid_until` defaults to N hours from now.
- **Check (gate)** — `GET /visitor-passes/check/{pass_code}` returns
  the pass if `valid_until > now` and `exit_time IS NULL`, else
  rejects. Successful check populates `entry_time` if it was null.

### 2.6 Sync API (`app/routes/sync.py`) — service side

- **Bootstrap** — happy path issues a `sync_token`, persists
  `(slug, license_key)` on the Society row. Replaying bootstrap with
  the same slug + license_key rotates the token (returns a new one and
  invalidates the old). Bootstrap with an invalid license_key (mock the
  license-server to deny) returns `{ok:false, error:'license_denied'}`.
- **Snapshot upsert** — `POST /api/v1/sync/snapshot` upserts by
  `(society_id, desktop_id)` for flats, residents, notices, polls.
  Sending the same payload twice yields identical DB state and no
  duplicate rows. Omitting a previously-sent flat marks it
  `active=false`.
- **Changes pull** — `GET /api/v1/sync/changes?since=<iso>` returns
  complaints, poll votes, and visitor passes created after `since`,
  scoped to the caller's `society_id`. Cross-society leakage test:
  Society A's sync_token cannot pull Society B's data even with a
  forged `society_id` query param.
- **Auth** — every endpoint except `/bootstrap` requires a valid
  `sync_token` header; missing or bad token → 401.

### 2.7 Wallet attachment (`app/wallet.py`)

- A society without a `license_key` returns `wallet_unconfigured` from
  the wallet-balance helper (matches the desktop's SMS-send path
  precondition).
- A society with a valid license_key proxies to the license-server's
  wallet endpoint (mock); response shape matches what the desktop
  expects.

### 2.8 Deploy smoke (manual, per release)

- `fly deploy` succeeds; `fly status` shows healthy.
- `https://rwagenie-web.fly.dev/healthz` returns 200 (add if not
  present).
- `https://rwagenie-web.fly.dev/` redirects unauthenticated to
  `/login`.
- Deploy preserves the Fly volume's SQLite (no schema reset on
  rolling restart).

---

## 3. Cross-repo sync contract

Lives in `rwagenie/tests/test_cloud_sync.py`. Goal: catch contract
drift between desktop's `CloudSyncService` and web's `app/routes/sync.py`
without running a real Fly deploy.

- Import the web app via `from app.main import app as web_app`
  (after temporarily adding `../rwagenie-web` to `sys.path`).
- Stand up a `fastapi.testclient.TestClient(web_app)` against an
  in-memory SQLite (`DATABASE_URL=sqlite://`).
- Monkeypatch the desktop's `requests` calls so they hit the
  TestClient instead of the live URL.
- Drive a full bootstrap → push → web-side write → pull cycle and
  assert the desktop ends up with the web-originated complaint.

Failure modes worth their own tests:
- Web schema adds a non-nullable column without a default → desktop
  push 500s instead of upserting → contract test catches it.
- Desktop sends a renamed field → web's pydantic `BootstrapRequest`
  rejects with 422 → contract test catches it.

---

## 4. Manual smoke checklist (every release)

Time-boxed to ~20 minutes total. Run after `build.bat` + `fly deploy`.

### Desktop

- [ ] Fresh install on Win 11 VM opens main window.
- [ ] Create a society, add a flat, add an owner, link them.
- [ ] Post a notice, file a complaint, create a poll with 3 options.
- [ ] Send a 2-recipient broadcast in **dry-run** mode (no wallet hit).
- [ ] Wallet page shows balance from license server.
- [ ] Cloud Sync page → bootstrap → push → success toast.
- [ ] Login as a non-admin user; verify viewer cannot delete a flat.
- [ ] Audit Log page lists the actions taken above with timestamps.

### Web

- [ ] Visit Fly URL → /login.
- [ ] Request OTP for the resident phone created above; receive SMS
      (or check `dev.db.otps` in staging).
- [ ] Verify OTP → land on dashboard with correct flat + notice.
- [ ] File a complaint via web; pull on the desktop; complaint appears
      in Complaints page with `origin=web` indicator.
- [ ] Vote on the poll via web; desktop Polls page shows tally update
      after pull.

---

## 5. CI suggestion

Two GitHub Actions workflows (one per repo):

- `rwagenie/.github/workflows/test.yml`:
  - Checkout rwagenie + Aiccounting as a sibling (matrix or
    submodule-less clone step).
  - `pip install -r ../Aiccounting/requirements.txt -r requirements.txt`.
  - `python -m unittest discover tests -v`.

- `rwagenie-web/.github/workflows/test.yml`:
  - `pip install -r requirements.txt pytest`.
  - `pytest tests/ -v`.

Sync contract tests run in the desktop workflow with rwagenie-web
checked out as an additional step. Both pipelines block merge to main.

---

## 6. Cloud Sync test runbook (detailed)

This is the hands-on procedure to verify cloud sync end-to-end when it
isn't working. Use it on every release that touches `cloud_sync.py` (desktop)
or `app/routes/sync.py` (web).

### 6.0 What the Fly.io server needs

For cloud sync to work, the Fly app `rwagenie-web` needs:

| Item | How to set | Required for sync? |
|---|---|---|
| Volume `rwagenie_web_data` at `/data` | `fly volume create rwagenie_web_data --size 1 --region bom` | Yes — SQLite DB lives there. Without it, redeploys wipe sync_tokens and societies. |
| `SECRET_KEY` secret | `fly secrets set SECRET_KEY=$(python -c "import secrets;print(secrets.token_urlsafe(32))")` | Yes — `_prod_safety_check()` in `app/main.py:44` exits if this is the default. |
| `SMS_API_KEY`, `SMS_SENDER_ID` secrets | `fly secrets set SMS_API_KEY=... SMS_SENDER_ID=...` | No for sync; yes for resident OTP login. |
| `LICENSE_SERVER_URL` env (optional) | Default `https://accgenie-license-in.fly.dev` | Only override for staging/self-host. |
| Outbound egress Fly → license server | Allowed by default | Yes — `/api/v1/sync/bootstrap` calls `{LICENSE_SERVER_URL}/api/v1/license/validate`. |

Pre-flight sanity check:
```
fly status -a rwagenie-web
fly secrets list -a rwagenie-web
fly volumes list -a rwagenie-web
curl https://rwagenie-web.fly.dev/healthz          # → "ok"
```

### 6.1 Likely failure modes

1. **Demo/dev license** — `cloud_sync.py:143` rejects `DEMO` and
   `ACCG-DEV-FULL` before hitting the server.
2. **License server returns `valid:false`** — license not registered
   with `product='rwagenie'`. Desktop shows `License not valid: …`.
3. **Fly machine cold-start** — `auto_stop_machines='stop'` +
   `min_machines_running=0`. First push of a big snapshot can exceed
   the 60s timeout on a cold start. Hit `/healthz` first to warm.
4. **Volume not mounted** — `Society.sync_token` is reissued on every
   bootstrap, but disappears on each deploy if `/data` is ephemeral.
   Push then 401s.

### 6.2 Test 1 — bootstrap

1. Open Cloud Sync page in desktop. Confirm `⚠ Not bootstrapped`.
2. Click **Activate cloud sync**.
3. Pass: status `✓ Bootstrapped`, server URL set, slug populated.
4. Verify on Fly:
   ```
   fly ssh console -a rwagenie-web -C "sqlite3 /data/rwagenie_web.db \
     'select id, slug, name, license_key, length(sync_token), \
      last_pushed_at from societies;'"
   ```
   Expect one row with a 43-char sync_token.

Failure → error message decoder:
- `Couldn't reach the sync server` → desktop ↔ Fly network or cold machine.
- `Couldn't reach the license-server` → Fly ↔ license-server. `fly logs`.
- `License not valid: …` → license rejected by license-server.
- `bootstrap_failed` (no msg) → unhandled exception, check `fly logs`.

### 6.3 Test 2 — push snapshot

1. Seed desktop: 2 flats (A-101, A-102), 2 owners linked as primary,
   1 pinned notice, 1 poll with 3 options.
2. Cloud Sync → **Sync now**.
3. Pass: `flats_upserted:2`, `residents_upserted:2`, `notices_upserted:1`,
   `polls_upserted:1`.
4. Verify on cloud:
   ```
   fly ssh console -a rwagenie-web -C "sqlite3 /data/rwagenie_web.db \
     'select count(*) from flats; select count(*) from residents; \
      select count(*) from notices; select count(*) from polls;'"
   ```
5. Idempotency: Sync now again → counts unchanged, `last_pushed_at` advances.
6. Soft-delete: delete one flat on desktop → Sync now → cloud row has `active=0`.

### 6.4 Test 3 — resident login surfaces pushed data

1. Set the seeded owner's phone to a real mobile (or set `DEV_SMS_LOG=1`
   and read the OTP from `fly logs`).
2. Visit `https://rwagenie-web.fly.dev/` → enter phone → OTP.
3. Pass: dashboard shows flat number, pinned notice, `outstanding_inr`
   matches desktop's ledger Dr balance.

### 6.5 Test 4 — pull (web → desktop)

1. As resident, file a complaint via the web; vote on the poll.
2. Desktop → Sync now.
3. Pass: result shows `complaints:1` under Pulled; Complaints page on
   desktop shows the web-filed complaint with `cloud_id` populated
   (`select id, cloud_id, title from rwa_complaints`).
4. Known v0.1 deferral: poll votes and visitor passes do not flow back
   to desktop (`cloud_sync.py:401, :408`). Don't fail on that.

### 6.6 Test 5 — admin → resident round-trip on a complaint

1. Desktop: open the web-filed complaint, set status RESOLVED, add notes.
2. Sync now → expect `complaints_updated:1`.
3. Resident refreshes complaints page → sees RESOLVED + notes.

### 6.7 Test 6 — token rejection / re-bootstrap

1. Simulate token loss:
   ```
   fly ssh console -a rwagenie-web -C "sqlite3 /data/rwagenie_web.db \
     \"update societies set sync_token='' where slug='YOUR-SLUG';\""
   ```
2. Desktop → Sync now. Expect: `Sync token rejected — re-activate cloud sync.`
3. Click **Re-activate cloud sync** → bootstrap re-runs → Sync now succeeds.

### 6.8 What to capture when sync misbehaves

```
type %APPDATA%\RWAGenie\logs\app.log | Select-Object -Last 100
fly logs -a rwagenie-web --since 10m
fly ssh console -a rwagenie-web -C "sqlite3 /data/rwagenie_web.db \
  '.schema societies' ; sqlite3 /data/rwagenie_web.db \
  'select * from societies;'"
```

Those three together pin down which leg of the handshake broke.

---

## 7. Known gaps / accepted risks for v0.1

- No load test on the web tier — single Fly instance + SQLite is the
  intentional v0.1 sizing. Revisit at >50 concurrent residents or
  >500 flats in one society.
- No multi-writer conflict resolution in sync — two desktops editing
  the same society are out of scope; last-writer-wins documented.
- WhatsApp / document storage / vendor management tests deferred —
  features themselves are PRO-tier and not in v0.1.
- Browser matrix on the web side: tested on current Chrome and
  Safari iOS only. Edge / Firefox issues filed as found, not gated.
