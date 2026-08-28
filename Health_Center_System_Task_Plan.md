# Health Center System — Task Plan

A phased breakdown of the project into tasks and subtasks. Suggested order top to bottom — later phases depend on earlier ones. Check items off as you go.

*Updated to reflect confirmed decisions: desktop app, single location, receptionist/admin roles only, fixed-but-editable doctor split, immutable transactions, optional file attachments (path reference only), English/Arabic with RTL, custom date-range reporting, offline flash-drive backups, and GitHub-based self-updates from a public repo.*

---

## Phase 0 — Project setup

- [ ] Create the project repository on GitHub (public — confirmed safe since no patient/financial data is ever published there)
- [ ] Set up a Python virtual environment and `requirements.txt`
- [ ] Decide project folder structure (e.g. `/gui`, `/logic`, `/data`, `/updater`)
- [ ] Install core dependencies: SQLAlchemy, psycopg2 (Postgres driver), bcrypt or argon2-cffi, requests
- [ ] Choose a GUI framework that supports right-to-left (RTL) layout for Arabic (confirm this before building any screens in Phase 4)
- [ ] Set up a local PostgreSQL instance for development
- [ ] Add a `.gitignore` (exclude `.env`, `__pycache__`, build artifacts)
- [ ] Create a `.env`-based config system for DB credentials and secrets (never hardcode)
- [ ] Write the setup script that creates the first admin account at installation (no in-app "create first admin" flow)

---

## Phase 1 — Data layer

- [ ] Define SQLAlchemy models: `Patient`, `User`, `Doctor`, `Transaction`, `Attachment`, `AuditLog`
- [ ] `Doctor` model includes `standard_percentage` (the standing/annual split rate) and `active`
- [ ] `Transaction` model stores `doctor_percentage`/`center_percentage` copied from the doctor at the time of the transaction (not a live reference) — so a later rate change never alters past records
- [ ] `Attachment` model stores `file_path` (local filesystem reference) and `patient_id` — not the file itself
- [ ] Write initial database migration (Alembic recommended for schema versioning)
- [ ] Add constraints: unique username on `User`, foreign keys on `Transaction` (patient_id, doctor_id, recorded_by), foreign key on `Attachment` (patient_id)
- [ ] Add a database-level rule or application check preventing patient deletion when the patient has any transactions (deactivate instead — see Phase 2.1)
- [ ] Decide UUID vs. auto-increment integer primary keys and apply consistently
- [ ] Write a seed script for test data (fake patients, doctors, users, transactions) for development
- [ ] Test raw CRUD operations against each model before building logic on top

---

## Phase 2 — Business logic layer

### 2.1 Patient logic
- [ ] Create patient (with field validation: required fields, phone/email format)
- [ ] Edit patient profile (must route through the update-and-log function, see 2.3)
- [ ] Fetch patient by ID / search by name or phone
- [ ] Delete patient — only when no transactions exist; block deletion (and prompt to deactivate instead) if any exist
- [ ] Deactivate patient (soft-disable, used whenever hard deletion isn't allowed)
- [ ] Attach a file reference to a patient (store path + description, not the file)
- [ ] Open an attachment — resolve the stored path and launch it in the OS's default viewer; handle the case where the path no longer resolves (e.g. file moved, or opening from a different desk than it was attached from)

### 2.2 Financial logic
- [ ] Build the split calculator: input = total amount + doctor's `standard_percentage` → output doctor_amount, center_amount
- [ ] Use `Decimal` throughout — no floats anywhere in this module
- [ ] Handle rounding rules explicitly (e.g. round to 2 decimal places, decide who absorbs rounding remainders)
- [ ] Write a function to record a new transaction (validates input, snapshots the doctor's current percentage onto the transaction, saves, logs)
- [ ] Enforce transaction immutability at the logic layer — no update/delete function should exist for a saved transaction
- [ ] Design and build the correction path for mistaken transactions: an "adjustment" entry type that references the original transaction rather than editing or deleting it (open design item — confirm exact shape with client before building)
- [ ] Write reporting queries filterable by an arbitrary custom date range (e.g. 15 Nov–23 Dec), not just fixed periods
- [ ] Write per-doctor and center total reports for a given date range
- [ ] Write a function to update a doctor's `standard_percentage` (goes through the update-and-log function, so rate changes are auditable)

### 2.3 Audit logging
- [ ] Write a single reusable "update and log" function: takes old row, new values, user id → applies change + writes audit_log entries
- [ ] Make sure every write path (patient edits, doctor rate edits) goes through this function — no direct writes elsewhere
- [ ] Write a function to fetch audit history for a given record (for an "edit history" view)
- [ ] Confirm transactions are excluded from this function's "edit" path entirely, since they're append-only (see 2.2)

### 2.4 Access control
- [ ] Implement the two confirmed roles — receptionist and admin — and what each can do (e.g. only admin manages users and doctor rates)
- [ ] Write a permission-check function used before sensitive actions
- [ ] Decide and implement what happens when a user without permission attempts a restricted action

### 2.5 Localization
- [ ] Externalize all UI-facing strings (no hardcoded English text in logic or GUI code) to support English/Arabic switching
- [ ] Confirm number, date, and currency formatting behave correctly in both languages

---

## Phase 3 — Authentication

- [ ] Build user creation (admin-only): username + password → hash with bcrypt/argon2, store
- [ ] Build login function: verify username + password against stored hash
- [ ] Implement session handling (how the GUI remembers who's logged in during a session)
- [ ] Add account lockout or throttling after repeated failed login attempts
- [ ] Build a "change password" flow
- [ ] Build an admin view to deactivate a user account (soft-disable, not delete)

---

## Phase 4 — GUI

*(Desktop application per front-desk PC — confirmed. Must support English/Arabic with RTL layout.)*

- [ ] Login screen
- [ ] Patient list / search view
- [ ] Patient profile view (view + edit mode, delete/deactivate actions, attachments list)
- [ ] New transaction / billing entry screen (shows calculated doctor/center split before saving; no edit mode, since transactions are final)
- [ ] Adjustment entry screen, once the correction mechanism (2.2) is designed
- [ ] Financial reports view with custom date-range picker, plus per-doctor and center totals
- [ ] Edit-history view for a given patient or doctor record (reads from audit_log)
- [ ] Doctor administration screen (admin-only: add doctors, update split percentages)
- [ ] User administration screen (admin-only: create/deactivate receptionist accounts)
- [ ] Language switcher (English/Arabic) with correct RTL layout behavior
- [ ] Basic error handling and validation messages in the UI (not just the logic layer)

---

## Phase 5 — Self-update system

- [ ] Package the app with PyInstaller into a single executable
- [ ] Set up a public GitHub repository and Releases as the distribution point; publish a test release
- [ ] Write the version-check function (query the GitHub Releases API's `/releases/latest` endpoint directly, compare tag to local version — no separate metadata store needed)
- [ ] Write the download function (fetch the release asset to a temp folder)
- [ ] Publish a checksum alongside each release and write the verification step
- [ ] Write the separate updater helper (waits for main app to close, swaps files, relaunches)
- [ ] Test a full update cycle end-to-end: old version → detects → downloads → verifies → installs → relaunches
- [ ] Decide and implement update timing (check on startup vs. prompt to restart) so it never interrupts an active transaction

---

## Phase 6 — Testing & hardening

- [ ] Unit tests for the split calculator (edge cases: rounding, 0%, 100%, odd percentages)
- [ ] Unit tests for the audit logging function (confirm old/new values are captured correctly)
- [ ] Unit tests confirming a transaction cannot be edited or deleted through any code path
- [ ] Unit tests for patient deletion (confirm it's blocked whenever transactions exist)
- [ ] Test concurrent access (two receptionists editing at once) against PostgreSQL
- [ ] Test what happens on a failed/interrupted self-update (should not corrupt the working install)
- [ ] Basic security pass: confirm passwords are never logged or displayed, confirm SQL is parameterized (SQLAlchemy handles this by default — verify no raw string queries were added)
- [ ] Backup and restore test using the actual offline flash-drive process (Phase 7), not just a database dump on disk
- [ ] Test attachment behavior when the file path doesn't resolve (moved/missing file, or opening from a different desk)
- [ ] Test the app in both English and Arabic, including RTL layout, on real screens

---

## Phase 7 — Deployment

- [ ] Set up the production PostgreSQL database (self-hosted or paid managed tier — hosting choice still open, see below)
- [ ] Build the automatic offline backup job: writes to a connected flash drive on schedule, and alerts (e.g. on next admin login) if the drive isn't present when a backup was due
- [ ] Document and test a restore procedure from the flash-drive backup — not just the backup step itself
- [ ] Decide and implement backup rotation/redundancy (single drive vs. a second rotating drive)
- [ ] Build and publish the first production release on GitHub
- [ ] Install on one front-desk machine as a pilot before rolling out to all
- [ ] Document a rollback procedure in case a release causes a problem
- [ ] Define and communicate a data retention policy for patient/financial records and the audit log
- [ ] Train receptionists on login, patient editing, transaction entry, and using attachments

---

## Open decisions to resolve before/during the relevant phase

- [ ] Primary database hosting: self-hosted PostgreSQL vs. a paid managed tier (must accommodate the offline flash-drive backup requirement)
- [ ] Shared/network file path convention for attachments, so a file attached at one desk is visible from another (needed before Phase 2.1/4 attachment work)
- [ ] Exact design of the transaction-correction/adjustment mechanism (needed before Phase 2.2 correction work and the Phase 4 adjustment screen)
- [ ] Full list of required financial reports beyond custom date-range filtering (useful before building the Phase 4 reports view)
- [ ] Data retention period for patient/financial records and the audit log
- [ ] Backup rotation/redundancy approach (single vs. multiple flash drives)
