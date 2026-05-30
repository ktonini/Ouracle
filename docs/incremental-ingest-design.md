# Design: Faster / Incremental Oura ZIP Ingest

Status: Ready to implement
Owner: TBD
Last updated: 2026-05-30
Spec: [`docs/incremental-ingest-spec.md`](./incremental-ingest-spec.md)

This document turns the incremental-ingest **spec** into a concrete, implementation-ready
**design**: schema, algorithms, code-level changes, transaction model, rollout, and a full
test plan. Every spec requirement (`G*`, `C*`, `T*`, `F*`, `U*`, `S*`, `M*`, `R*`, `O*`,
`TC*`) is mapped to a concrete mechanism in §13 (traceability).

---

## 1. Summary of the approach

The ingest pipeline gains a **detection layer** that decides, per export and per file, how
much work to do. Three cheap-to-expensive signals compose:

1. **Whole-ZIP fingerprint** (fast path). Hash the downloaded ZIP. If it equals the last
   successfully-ingested ZIP fingerprint, skip parsing entirely → "no new data" in well
   under a second (satisfies G1, M1, S3).
2. **Per-file fingerprint.** For each CSV in the export, hash its bytes. Unchanged files
   are not parsed at all. This is what makes a "+1 day" export cheap: `heartrate.csv`,
   `temperature.csv`, `sleepmodel.csv` only get re-parsed when they actually changed
   (G2, M2/M3).
3. **Per-tier row processing.** For files that *did* change:
   - **High-frequency** (`HeartRate`/`Temperature`/`RingBattery`, keyed by `timestamp`):
     parse only rows newer than a **DB-derived high-water mark minus a trailing window**
     `W` (append-mostly; T1/T2).
   - **Daily summaries & sessions** (keyed by `day`/`id`): parse the file, then **compare
     each incoming row's business content against the stored row** and write only
     new/changed rows. This is inherently correction-aware (C2) and small/bounded.
   - **Metadata & user tags**: always re-processed (cheap; E1).

Two correctness prerequisites from spec §5.5 are implemented first, because all
key/content comparison depends on them:

- **Deterministic keys** replace `uuid.uuid4()` so the same business row yields the same
  key across exports.
- **No PK churn** on day-keyed entities, so an unchanged re-ingest does not mutate rows.

Detection state is persisted in a new additive SQLite table and committed **only after**
row writes succeed (C4). High-water marks are **derived live from the DB** rather than
persisted, which keeps them self-healing after a DB restore (R3).

Everything is behind a config flag (`incremental_ingest_enabled`) with a force-full
escape hatch (O3/O4/O6).

---

## 2. Current state (grounding)

Key facts established from the code, with the files this design touches:

| Concern | Today | File |
| --- | --- | --- |
| ZIP → dir → per-file processors | `parse_zip` extracts to temp, `parse_directory` reads **every** CSV | `backend/src/ingestion/manager.py` |
| Generic upsert | `_upsert(model, data, index_elements)`, `ON CONFLICT DO UPDATE` with update set = *all columns except conflict key*; **commits per batch** | `backend/src/ingestion/base.py:99` |
| CSV read | `_read_csv_robust` auto-inserts `str(uuid.uuid4())` when `header[0]=='id'` and a field is missing | `backend/src/ingestion/base.py:25` |
| UUID minting | processors do `str(row.get('id', uuid.uuid4()))` / `uuid.uuid4()` fallbacks | `processors/*.py` |
| Runner | `ingest_zip_blocking` returns `(before_latest, after_latest, error)`; `ingest_zip_async` returns `advanced: bool` | `backend/src/ingestion/runner.py` |
| Freshness/status | `_latest_day`, `ingest_advanced_data`, `apply_post_ingest_result`, `SyncFreshness` | `backend/src/insights/sync_freshness.py` |
| Sync flow | `run_full_sync_task` ingests ready export; if not advanced, requests one fresh export (`skip_ready_download=True`) | `backend/src/api/routes.py:120` |
| Config store | JSON files via `config_manager` (`oura_config.json`), backfilled by `_ensure_config` | `backend/src/config.py` |
| Schema | `Base.metadata.create_all` only — **new tables auto-create; column ALTERs do not happen** | `backend/src/database.py:61` |
| Tests | `db_session` in-memory fixture; **no ZIP/CSV fixtures, no parser tests** | `backend/tests/conftest.py` |

Entities and conflict keys (unchanged by this design):

| Tier | Entities | Conflict key | `id` PK? |
| --- | --- | --- | --- |
| High-frequency | `HeartRate`, `Temperature`, `RingBattery` | `timestamp` | no |
| Daily summary | `Sleep`, `Activity`, `Readiness`, `Resilience`, `CardiovascularAge` | `day` (unique) | yes, generated |
| Session/event | `SleepSession`, `Workout`, `Meditation` | `id` | yes, generated |
| Metadata | `RingConfiguration`, `Tag` | `id` | yes, generated |

---

## 3. Detection state store

### 3.1 New table (additive — auto-created by `create_all`)

Add to `backend/src/models.py`:

```python
class IngestState(Base):
    """Key/value store for incremental-ingest detection state.

    Additive table. Rows are written transactionally with ingest (see §6) and may be
    cleared wholesale by the force-full escape hatch (§9). Values are JSON-encoded text.
    """
    __tablename__ = "ingest_state"

    key: Mapped[str] = mapped_column(String, primary_key=True)
    value: Mapped[Optional[str]] = mapped_column(String, nullable=True)  # JSON text
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
```

Because it lives in `oura_database.db`, it is committed in the same SQLite transaction as
row writes (C4, R8). It is created by the existing `init_db()` → `create_all` path with no
migration needed for the table itself (O1).

### 3.2 Keys stored

| Key | Value (JSON) | Purpose |
| --- | --- | --- |
| `last_zip_fingerprint` | `{"sha256": "...", "size": 12345}` | whole-ZIP fast path (§5.1, S3) |
| `file_fingerprints` | `{"heartrate.csv": {"sha256": "...", "size": N}, ...}` | per-file skip (§5.2) |
| `schema_normalized_version` | `{"version": 1}` | one-time key-normalization migration guard (§9.3, O7) |

**Deliberately NOT stored: high-water marks.** They are recomputed from the DB at ingest
start (`SELECT max(timestamp)` per high-frequency table). Deriving them live means a DB
restore/rollback cannot leave a watermark ahead of the data (R3); the only persisted
"skip" signal is the fingerprint set, which the escape hatch can clear.

A thin accessor module wraps this table:

```python
# backend/src/ingestion/state.py
def get_state(db, key, default=None) -> Any            # json.loads(value) or default
def set_state(db, key, value) -> None                  # flush only; caller commits
def clear_detection_state(db) -> None                  # delete fingerprint keys (escape hatch)
```

`set_state` **flushes but does not commit** so it joins the surrounding transaction (§6).

---

## 4. Deterministic keys & no PK churn (spec §5.5 — prerequisite)

This must ship before/with skip logic; otherwise every comparison is poisoned by churning
UUIDs (R4).

### 4.1 Synthetic key helper

Add to `IngestionBase` (`base.py`):

```python
import hashlib

def _synthetic_id(self, entity: str, fields: list) -> str:
    """Deterministic key from natural identifying fields.

    Stable across exports for the same business row. Normalizes values (str, stripped,
    lowercased datetimes via isoformat) so reparsing never changes the key.
    """
    parts = []
    for f in fields:
        if f is None:
            parts.append("")
        elif isinstance(f, (datetime, date)):
            parts.append(f.isoformat())
        else:
            parts.append(str(f).strip())
    digest = hashlib.sha256((entity + "|" + "\x1f".join(parts)).encode("utf-8")).hexdigest()
    return f"{entity}:{digest[:32]}"
```

### 4.2 Per-entity key rules

| Entity | When Oura `id` present | When `id` missing → synthetic fields |
| --- | --- | --- |
| `SleepSession` | use `id` | `(day, bedtime_start, type)` |
| `Workout` | use `id` | `(day, start_time, activity)` |
| `Meditation` | use `id` | `(day, start_time, type)` |
| `Tag` | use `id` | `(start_time, tag_type_code, comment)` |
| `RingConfiguration` | use `id` | `(firmware_version, hardware_type, color, size)` |
| `Sleep`/`Activity`/`Readiness`/`Resilience`/`CardiovascularAge` | n/a (conflict on `day`) | **`id = _synthetic_id(table, [day])`** always |

Day-keyed entities always derive `id` from `day`. Because the value is deterministic,
re-ingesting an unchanged day produces the **same** `id`, so even though `_upsert` keeps
`id` in the `ON CONFLICT DO UPDATE` set, it rewrites it to an identical value → no churn
(satisfies §5.5 item 2 and M1 without touching `_upsert`'s update-set logic).

> `Workout`/`Meditation` synthetic fields use `start_datetime`/`type`/`activity` parsed
> from the CSV (`activity.py`). Confirm `workout.csv` exposes an `activity` column during
> implementation; if absent, fall back to `(day, start_time, intensity)`. This is the one
> field-name detail to verify against a real export.

### 4.3 Stop `_read_csv_robust` from minting UUIDs

Change `base.py:77` so a missing leading `id` field is filled with **empty string**, not a
UUID. The processor then derives the deterministic key:

```python
# was: parts.insert(0, str(uuid.uuid4()))
if len(parts) == len(header) - 1 and header[0] == 'id':
    parts.insert(0, "")     # let the processor derive a deterministic key
```

Each processor's `str(row.get('id', uuid.uuid4()))` / `uuid.uuid4()` fallback is replaced
with: "use Oura id if non-empty/non-NaN, else `_synthetic_id(...)`". Example for
`SleepSession`:

```python
oura_id = row.get('id')
if pd.isna(oura_id) or str(oura_id).strip() in ("", "nan"):
    sid = self._synthetic_id("sleep_session", [self._parse_date(row.get('day')),
                                               bedtime_start, row.get('type')])
else:
    sid = str(oura_id)
sleep = SleepSession(id=sid, ...)
```

`process_stress` (the outlier that manually creates placeholder `Activity` rows with
`uuid.uuid4()`) must also use `_synthetic_id("activity", [day])` so its placeholder shares
the same key as the real `Activity` row for that day.

### 4.4 Content comparison excludes volatile columns

Change detection (daily/session tiers, §5.3) compares **business columns only**, excluding:

- identity columns: `id`
- ingest-derived/volatile: none currently beyond `id` once timestamps are normalized.

Define per-model `CONTENT_COLUMNS` (all columns minus the exclude set) once, in `state.py`
or as a model classmethod, and reuse for both comparison and any future hashing.

---

## 5. Detection algorithm

### 5.1 Whole-ZIP fast path (runner level)

In `ingest_zip_blocking`, before parsing:

```
zip_fp = sha256_of_file(zip_path)              # one streaming pass
if incremental_enabled and not force_full:
    last = get_state(db, "last_zip_fingerprint")
    if last and last["sha256"] == zip_fp["sha256"]:
        return IngestOutcome(skipped_identical_zip=True, before=latest, after=latest, ...)
```

This is the M1/S3 fast path: hashing even a few-hundred-MB ZIP is ~1 s; no extraction, no
parse. Outcome reports `advanced=False`, `changed=False`.

### 5.2 Per-file fingerprint (manager level)

`parse_directory` gains a fingerprint gate. For each candidate CSV:

```
fp = sha256_of_file(path)                       # size + sha256
prev = file_fingerprints.get(filename)
if incremental_enabled and not force_full and prev == fp and not _in_trailing_scope(filename):
    skip file (record processed=False, skipped=True)
else:
    process file with the tier strategy below
    new_file_fingerprints[filename] = fp        # staged, committed at end (§6)
```

Notes:
- `_in_trailing_scope` is always `False` for whole-file fingerprint skipping **except** we
  never skip user-authored `enhancedtag.csv` (E1) — it is always processed.
- Files **absent** from the export are left untouched: we do not clear their fingerprint
  and do not delete rows (C3, R2, TC6).

### 5.3 Tier strategies for files that are processed

The processors are refactored to accept a small `IngestContext` carrying `db`, the live
high-water marks, the trailing window `W`, and per-run counters. Each processor returns
counts `(inserted, updated, unchanged, skipped)`.

**High-frequency** (`process_heart_rate`, `process_temperature`, `process_ring_battery`):

```
hwm = high_water_marks[entity]                  # max(timestamp) from DB, computed at start
cutoff = (hwm - timedelta(days=W)) if hwm else None
for row in df:                                  # scan all rows, do NOT early-exit (R6)
    ts = parse_datetime(row.timestamp)
    if cutoff is not None and ts < cutoff:
        skipped += 1; continue                  # provably older than re-process window
    records.append(...)
batch_upsert(...)                               # ON CONFLICT(timestamp) DO UPDATE (C5)
```

The trailing window re-includes the last `W` days so late HR/temperature samples and
re-encodings within the window still land (T1). Backfills older than `W` days are still
caught because a backfilled file is a *changed file* → its fingerprint differs → it is
processed; the cutoff only filters within an already-changed file, and a backfill that
predates the cutoff is rare for append-mostly series. **Safety belt:** if
`force_full`/cold-start, `cutoff=None` (process everything). For genuine old-backfill
correctness on high-frequency data, see Open Question Q3 resolution (§12) — we additionally
treat "row count in file decreased vs. last fingerise" as a signal to widen the window.

**Daily summaries & sessions** (`process_sleep`, `process_activity`, `process_readiness`,
`process_resilience`, `process_cardiovascular_age`, `process_sleep_session`,
`process_workout`, `process_meditation`):

```
build all candidate ORM rows from the (changed) file
keys = [r key]                                  # day or id
existing = {key: row} from one SELECT ... WHERE key IN (keys)
to_write = []
for r in candidates:
    old = existing.get(r.key)
    if old is None:           inserted += 1; to_write.append(r)
    elif content_differs(old, r, CONTENT_COLUMNS): updated += 1; to_write.append(r)
    else:                     unchanged += 1
upsert(model, to_write, [conflict_key])         # only new/changed rows written
```

`content_differs` compares the `CONTENT_COLUMNS` (§4.4). This is what classifies a run as
**corrections-only** (updated>0, inserted==0, latest_day unchanged) for U3 messaging, and
avoids write amplification. These files are small except `sleepmodel.csv`, which is gated
by the per-file fingerprint (§5.2) so it is only parsed when it actually changed (R7).

**Metadata & tags** (`process_ring_configuration`, `process_tag`): always processed
(per-file fingerprint may still skip `ringconfiguration.csv`; `enhancedtag.csv` is never
skipped, E1). Same content-compare path so unchanged tags don't churn.

### 5.4 Cold start / no detection state (F1)

If `get_state(db, "file_fingerprints")` is empty (fresh install or first run after
upgrade), `force_full` behavior applies for this run: no skips, no cutoffs (full ingest),
then fingerprints + normalized-version are recorded. The first post-upgrade run is allowed
to be slow (M5).

---

## 6. Transaction & atomicity model (C4, R8)

Goal: detection state (zip + file fingerprints) must only advance after the corresponding
rows are durably committed, and a crash must leave detection state unchanged so the next
run re-attempts the same work.

Current `_upsert` commits per batch. We keep that (it bounds memory and is idempotent), but
make the **fingerprint writes the last thing that happens**, gated on full success:

```python
# ingest_zip_blocking (revised)
before = _latest_day(db)
parser = OuraParser(db, ctx)            # ctx carries counters + staged fingerprints
parser.parse_zip(zip_path)              # per-batch commits of ROWS happen inside
after = _latest_day(db)
# Only now, after all row work succeeded, persist detection state in one commit:
set_state(db, "file_fingerprints", {**old_fps, **ctx.new_file_fingerprints})
set_state(db, "last_zip_fingerprint", ctx.zip_fp)
db.commit()
return IngestOutcome(before, after, ctx.counts, error=None)
```

Failure semantics:
- Exception mid-parse → `except` rolls back the *current* uncommitted batch and **does not**
  write fingerprints. Already-committed batches remain (idempotent on re-run). Fingerprints
  stay at their previous value → next run re-evaluates those files and finishes the work
  (C4, TC9). This matches the existing partial-progress behavior; we only guarantee that
  *skip state never runs ahead of data*.
- Partial/truncated export (C3, R2): missing files keep their old fingerprints (not
  cleared); files with fewer rows still only ever upsert (never delete); `last_zip_fingerprint`
  is updated to the partial zip's hash **only on success**, which is fine because a later
  full export will have a different hash and re-process.

> Optional hardening (recommended): wrap the whole ingest in a single transaction
> (`begin()` once, commit once) instead of per-batch commits, so even partial rows roll
> back on failure. This is a clean win for atomicity but changes memory characteristics for
> very large first-run ingests; keep per-batch commits for the cold/full path and use a
> single transaction for incremental (small) runs. Decision recorded in §12 Q-impl.

---

## 7. Ingest outcome & user-facing messaging (spec §6)

### 7.1 Structured outcome

Replace the runner's tuple with a dataclass (internal; the public `advanced` bool is
preserved, U5):

```python
@dataclass
class IngestOutcome:
    before_latest: Optional[date]
    after_latest: Optional[date]
    inserted: int            # new rows across all entities
    updated: int             # changed existing rows (corrections)
    unchanged: int
    files_processed: int
    files_skipped: int
    skipped_identical_zip: bool
    error: Optional[Exception]

    @property
    def advanced(self) -> bool:
        return ingest_advanced_data(self.before_latest, self.after_latest)

    @property
    def changed(self) -> bool:           # corrections happened but no new latest day
        return self.inserted > 0 or self.updated > 0
```

`ingest_zip_async` still returns `bool` = `outcome.advanced` (U5/S1 contract intact). The
richer outcome flows into status/observability.

### 7.2 Messaging matrix (extends `apply_post_ingest_result`)

`apply_post_ingest_result(outcome, success_message=...)` produces:

| Scenario | `advanced` | `changed` | Message | `last_run` bumped? |
| --- | --- | --- | --- | --- |
| New day(s) added (U2) | true | true | `success_message` | yes |
| Corrections only (U3) | false | true | "Updated N existing day(s); no new days yet. Local data refreshed." | yes (U6) |
| Identical export (U1) | false | false (skip) | reuse "no new days were added — request a fresh Oura export and sync again" | no |
| Up to date, nothing changed | false | false | "No new days in this export — local data is already up to date." | no |
| Partial error | — | — | "Sync complete (partial: …)" | no |

This adds the **corrections-only** branch (U3) that today's binary model lacks. `last_run`
(→ `last_ingest_at`) is bumped on `advanced OR changed` (U6 recommendation); `days_behind`
is still computed from `latest_day` only, so a corrections-only run does not falsely change
the lag (U6).

### 7.3 Progress indication (U4)

`run_full_sync_task` and the runner emit distinct `Processing` statuses:
- "Checking what's new in this export…" (during fingerprint phase)
- "Importing N new day(s)…" / "Updating N corrected day(s)…" (during write phase)

So a sub-second skip reads as a deliberate fast check, not a stall.

### 7.4 Freshness read model (§6.2)

`SyncFreshness` is unchanged in shape; `last_ingest_at` semantics widen per the matrix
above. No client change required (desktop `useSyncFreshness`, Android `SyncFreshnessDto`
keep working). Optionally add `last_change_kind: "new" | "corrections" | "none"` for richer
UI later — **not required** for this change; flagged as a non-blocking follow-up.

---

## 8. Sync-flow integration (spec §7)

`run_full_sync_task` (`routes.py`) keeps its structure; the only changes:

- **S1 preserved:** the ready-export ingest still branches on `advanced`. A fast identical-zip
  skip returns `advanced=False`, so the fresh-export request still fires. A skip is never
  mistaken for success.
- **S3 short-circuit:** because the runner hashes the zip first, an identical ready export
  is detected without parsing — the existing `if advanced: return` / else-request-fresh
  logic is unchanged but now runs in ~1 s instead of minutes.
- **S2 loop bound preserved:** still at most one fresh-export request per sync. After the
  fresh export is downloaded, the second `ingest_zip_async` call is updated to surface the
  outcome message; if that zip is *also* identical (`skipped_identical_zip=True`), status
  becomes "Oura has not produced newer data yet" rather than implying success. No new loop
  is introduced.
- **S4 unaffected:** `last_export_request_at` and `sync_recovery.py` (`STUCK_AFTER=20m`)
  continue to govern the *download* phase. Faster ingest only reduces how often runs
  approach the threshold; verify recovery still triggers for stuck downloads (TI-recovery).

No change to `automation.py` / Playwright (N1).

---

## 9. Rollout, flags, migration (spec §11)

### 9.1 Feature flag (O3, O6)

Add config keys to `DEFAULT_CONFIG` (`config.py`), auto-backfilled by `_ensure_config`:

```python
"incremental_ingest_enabled": True,         # default on after TC11 passes (review decision)
"incremental_reprocess_window_days": 3,     # trailing window W (T3, Q1)
```

The runner/manager read these via `config_manager.get_config()`. Disabling the flag makes
the pipeline ignore detection state and behave exactly as today (O6 — no data fix-up,
fingerprints are simply unused). Reversibility is total because detection state is
non-destructive.

### 9.2 Escape hatch — force full re-ingest (O4)

- A `force_full: bool` parameter threads `runner → manager → processors`, disabling all
  skips and cutoffs and clearing fingerprints at the end of a successful run.
- Exposed via a new route `POST /api/ingest/rebuild` (and a Settings button) that runs the
  next ingest with `force_full=True` after calling `clear_detection_state(db)`. This is the
  R3 recovery path and must exist before enabling skipping by default.

### 9.3 One-time key normalization / dedup (O7, R4, §5.5)

Because existing rows carry random UUIDs, deterministic keys won't match them. Add a
hand-rolled, idempotent migration (there is no Alembic; mirror the JSON-config backfill
pattern) invoked from `init_db()`:

```python
# backend/src/ingestion/key_migration.py
def normalize_keys_if_needed(db):
    if get_state(db, "schema_normalized_version") == {"version": 1}:
        return
    # Day-keyed entities: rewrite id = synthetic(table, [day]) (unique day → no collisions)
    for Model, table in [(Sleep,"sleep"), (Activity,"activity"), (Readiness,"readiness"),
                         (Resilience,"resilience"), (CardiovascularAge,"cardiovascular_age")]:
        for row in db.query(Model).all():
            row.id = _synthetic_id(table, [row.day])
    # id-keyed entities: recompute synthetic id from natural fields, collapse duplicates
    for Model, table, fields_fn in SESSION_AND_META_SPECS:
        seen = {}
        for row in db.query(Model).order_by(Model.id).all():
            new_id = _synthetic_id(table, fields_fn(row))
            if new_id in seen:
                db.delete(row)            # collapse duplicate, keep first (latest by policy)
            else:
                seen[new_id] = row; row.id = new_id
    set_state(db, "schema_normalized_version", {"version": 1})
    db.commit()
```

- Runs once, guarded by the version marker; safe to re-run (TC8).
- MUST run before skip logic trusts keys. Ordering in `init_db()`: `create_all` →
  `normalize_keys_if_needed` → app start.
- Alternative offered to support: run the O4 escape hatch (full re-ingest) instead.

> SQLite note: rewriting a PK is an `UPDATE` of the `id` column; with `day`-unique tables
> there is no PK collision. For session/meta tables we delete-then-keep to satisfy the `id`
> PK. Wrap each model's migration in a savepoint so a failure on one table doesn't strand
> the rest.

### 9.4 Observability (O5)

Per run, log a single structured line and stash it in `IngestState["last_run_stats"]`:

```
ingest done: zip_skipped=false files_processed=4 files_skipped=9
  inserted=312 updated=2 unchanged=0 entities={heart_rate:300,...}
  hwm_cutoff=2026-05-27 duration_ms=2143 advanced=true
```

This lets us verify §8 targets in the field and debug reports.

---

## 10. File-by-file change list

| File | Change |
| --- | --- |
| `backend/src/models.py` | Add `IngestState` table. |
| `backend/src/ingestion/state.py` (new) | `get_state`/`set_state`/`clear_detection_state`, `CONTENT_COLUMNS`, `content_differs`, `sha256_of_file`. |
| `backend/src/ingestion/base.py` | Add `_synthetic_id`; stop UUID auto-insert in `_read_csv_robust`; (optional) single-transaction helper. |
| `backend/src/ingestion/manager.py` | `OuraParser.__init__(session, ctx)`; per-file fingerprint gate in `parse_directory`; pass `ctx` to processors; stage `new_file_fingerprints`. |
| `backend/src/ingestion/processors/sleep.py` | Deterministic keys; content-compare path; return counts. |
| `backend/src/ingestion/processors/activity.py` | Same; fix `process_stress` placeholder key. |
| `backend/src/ingestion/processors/readiness.py` | Same. |
| `backend/src/ingestion/processors/common.py` | High-frequency cutoff filter; deterministic keys for `Tag`/`RingConfiguration`; counts. |
| `backend/src/ingestion/runner.py` | Zip fingerprint fast path; build `IngestContext`; return `IngestOutcome`; commit detection state last; thread `force_full`. |
| `backend/src/insights/sync_freshness.py` | `apply_post_ingest_result(outcome)` + corrections-only message branch; `last_run` on `advanced or changed`. |
| `backend/src/api/routes.py` | Progress statuses; second-ingest message; `POST /api/ingest/rebuild`. |
| `backend/src/api/main.py` | Scheduled worker uses new outcome messaging (no behavior regression). |
| `backend/src/config.py` | Add the two config keys to `DEFAULT_CONFIG`. |
| `backend/src/database.py` | Call `normalize_keys_if_needed(db)` in `init_db()`. |
| `backend/src/ingestion/key_migration.py` (new) | One-time normalization/dedup (§9.3). |

The introduced `IngestContext` dataclass (in `state.py` or `runner.py`):

```python
@dataclass
class IngestContext:
    db: Session
    incremental_enabled: bool
    force_full: bool
    window_days: int                 # W
    high_water_marks: dict           # entity -> max timestamp (live from DB)
    file_fingerprints: dict          # previous (read-only)
    new_file_fingerprints: dict      # staged this run
    counts: Counter                  # inserted/updated/unchanged/skipped per entity
    zip_fp: dict
```

---

## 11. Test plan (spec §10)

### 11.1 New test infrastructure

There are no ZIP/CSV fixtures today. Add `backend/tests/helpers/oura_export.py`:

```python
def write_export(tmp_path, *, daily_sleep=None, heartrate=None, sleepmodel=None,
                 enhancedtag=None, ...) -> Path:
    """Write semicolon-delimited Oura CSVs into a dir, return a zipped path.

    Matches _read_csv_robust expectations (';' delimiter, optional leading 'id').
    Helpers build minimal valid rows; callers tweak a single field to model a
    correction/backfill/new-day.
    """
```

Plus a `seeded_db` fixture (file-based SQLite in `tmp_path`, since the runner opens its own
`SessionLocal`; use dependency injection of a session into `ingest_zip_blocking(db=...)` to
reuse the in-memory `db_session`).

### 11.2 Functional / correctness (must pass to ship)

| Test | Asserts | Spec |
| --- | --- | --- |
| `test_identical_reingest_noop` | second ingest writes 0 rows, `advanced=False`, `skipped_identical_zip=True`, DB byte-identical | TC1, C5 |
| `test_one_new_day` | only new day's rows written; older untouched; `advanced=True` | TC2 |
| `test_n_new_days` | all N land; older untouched | TC3 |
| `test_correction_to_existing_day` | changed daily row updated though `latest_day` flat; `changed=True`; corrections message | TC4, U3 |
| `test_backfill_older_day` | day older than `latest_day` inserted (HWM didn't hide it) | TC5 |
| `test_partial_export_no_regression` | missing files / fewer rows → no deletes, no fingerprint advance for missing files | TC6, C3 |
| `test_trailing_window_correction` | change within last `W` days detected even with matching file fingerprint (force the file to differ, or test the cutoff directly) | TC7, T1 |
| `test_deterministic_keys` | re-ingest of id-less `SleepSession`/`Workout`/`Meditation`/`Tag`/`RingConfiguration` → same key, no dupes, "unchanged"; day-keyed `id` stable across re-ingest | TC8, §5.5 |
| `test_key_migration_dedup` | old random-UUID rows collapse to deterministic keys; idempotent re-run | TC8, O7 |
| `test_crash_rollback_state` | raise mid-parse → fingerprints unchanged; re-run completes | TC9, C4 |
| `test_cold_start_full_ingest` | no state → full ingest, records fingerprints + version | TC10, F1 |
| `test_equivalence_from_scratch` | for TC1–TC7, incremental DB == from-scratch full ingest (modulo nondeterministic fields) | TC11, M6 |

`content_differs` and `_synthetic_id` also get focused unit tests (volatile-column
exclusion: a reparsed timestamp / re-derived id must NOT register as a change — §5.5 item 3).

### 11.3 Performance (§8, TP1/TP2)

`test_perf_scaling` on a large generated fixture (multi-year `heartrate.csv`): assert
unchanged-export ≪ +1-day ≪ cold ingest, and that "+1 day" time on a large vs small base DB
is comparable (time ∝ new data, not history). Use generous CI margins; assert
*relationships*, not absolute seconds.

### 11.4 Integration / flow (§7, §6)

| Test | Asserts | Spec |
| --- | --- | --- |
| `test_full_sync_identical_requests_fresh` | identical ready export → still requests fresh export; fresh also identical → terminates, no loop, "no newer data" message | TI1, S1, S2 |
| `test_status_messages_skip_vs_new_vs_corrections` | `apply_post_ingest_result` matrix (§7.2) | TI2, U1–U3 |
| `test_existing_suites_pass` | `test_ingest_runner.py`, `test_sync_freshness.py`, `test_action_cards.py` pass or are updated intentionally | TI3 |

---

## 12. Open questions — resolved defaults (spec §12)

- **Q1 (window `W`):** default **3 days**, single global value, config key
  `incremental_reprocess_window_days`. Per-entity windows are unnecessary given daily
  summaries use always-on content compare (correction-proof regardless of `W`); `W` only
  bounds high-frequency re-scan. Revisit per-entity only if field data shows sleep
  finalizing later than 3 days.
- **Q2 (corrections count as `advanced`?):** No to `advanced` (keeps the fresh-export
  decision correct, S1), but **yes to "successful ingest"** — bump `last_run` on
  `advanced or changed`, leave `days_behind` driven by `latest_day` (U6).
- **Q3 (detection granularity):** whole-ZIP hash + per-file hash + DB-derived per-entity
  high-water mark, with **content-aware compare for correction-prone entities** (daily +
  sessions) as the mandatory minimum for that tier. High-frequency old-backfill safety: if a
  changed high-frequency file's row count is **lower** than expected or contains rows older
  than `cutoff`, widen `cutoff` to the file's min timestamp for that file (cheap, rare).
- **Q4 (where state lives):** new **SQLite table** `ingest_state` in `oura_database.db`
  (not JSON config), so detection state is transactionally consistent with row writes (C4)
  and cleared atomically by the escape hatch. Config holds only the flag + window.
- **Q-impl (transaction model):** keep per-batch commits for cold/full ingest; persist
  fingerprints in a final commit after success (§6). Single-transaction incremental runs are
  a recommended hardening, decided during implementation review.

---

## 13. Requirement traceability

| Spec ID | Where satisfied |
| --- | --- |
| G1 / M1 | §5.1 whole-zip fast path |
| G2 / M2 / M3 | §5.2 per-file skip + §5.3 high-water cutoff |
| G3 / C1 / C2 / TC4 / TC5 / TC7 | §5.3 content compare + trailing window |
| G4 / U1–U4 | §7.2 messaging matrix, §7.3 progress |
| G5 / S1 / S2 / S3 | §8 sync-flow integration |
| C3 / R2 / TC6 | §5.2 (absent files untouched) + §6 (additive only) |
| C4 / R8 / TC9 | §6 transaction model |
| C5 / TC1 | idempotent upsert + §5.1 |
| C6 | conflict keys unchanged (§2 table) |
| T1–T3 | §5.3 cutoff + `incremental_reprocess_window_days` |
| F1 / M5 / TC10 | §5.4 cold start |
| §5.5 / R4 / TC8 | §4 deterministic keys + §9.3 migration |
| U5 | §7.1 `advanced` bool preserved |
| U6 / Q2 | §7.2 last_run rule |
| S4 | §8 (recovery untouched) |
| M4 | §5.3 daily content compare bounded by changed files + `W` |
| M6 / TC11 | §11.2 equivalence test |
| R3 | §3.2 DB-derived HWM + §9.2 escape hatch |
| R5 / R6 | §5.3 normalized parsed timestamps, full scan (no early exit) |
| R7 | §5.2 fingerprint gate on `sleepmodel.csv` + content compare |
| O1 / O2 | §3.1 additive table, §5.4 self-seeding |
| O3 / O6 | §9.1 flag |
| O4 | §9.2 escape hatch |
| O5 | §9.4 observability |
| O7 | §9.3 key migration |

---

## 14. Implementation sequencing

1. **Deterministic keys + no PK churn** (§4) and the one-time key migration (§9.3). Ship and
   verify `test_deterministic_keys`, `test_key_migration_dedup`, equivalence — *no skip logic
   yet*. This is independently valuable and de-risks everything else.
2. **`IngestState` table + `state.py`** (§3) and the `IngestContext`/`IngestOutcome` plumbing
   (§6/§7.1), still doing full work but recording fingerprints + counts.
3. **Per-file fingerprint skip + whole-zip fast path** (§5.1/§5.2). Largest perf win.
4. **High-frequency cutoff** (§5.3) and **daily/session content compare** (§5.3).
5. **Messaging matrix** (§7.2) + **sync-flow** statuses (§8) + **flag/escape hatch**
   (§9.1/§9.2) + **observability** (§9.4).
6. **Full test suite** (§11), flip `incremental_ingest_enabled` default on once TC11 passes.
