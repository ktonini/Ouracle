# Spec: Faster / Incremental Oura ZIP Ingest

Status: Draft for review
Owner: TBD
Last updated: 2026-05-30

## 1. Background

Cracked Oura syncs by automating Oura's "personal data export", downloading a ZIP
of CSV files, and ingesting them into a local SQLite database.

Today, every successful download triggers a full ingest:

- `OuraParser.parse_zip` extracts the archive to a temp directory.
- `parse_directory` re-reads **every** supported CSV and upserts each row into the
  database by its natural key (`day` for daily summaries, `id` for sessions/metadata,
  `timestamp` for high-frequency series) via SQLite `INSERT … ON CONFLICT DO UPDATE`.

Because Oura's export is a **full historical snapshot, not a delta**, every run
re-parses and re-upserts the entire history — including the large files
(`heartrate.csv`, `temperature.csv`, `sleepmodel.csv`, `ringbatterylevel.csv`).
The upsert keys prevent duplicate rows, but we still do the full work even when the
local database already contains everything in the export.

Observed effect: ingest can take several minutes (~5 min reported) even when no new
calendar day is added. Sync feels slow and wasteful, especially when the user
re-downloads an old export, when a sync completes but `latest_day` does not advance,
or when only one new day of data exists.

### Current freshness model (for reference)

- `_latest_day(db)` = `max(day)` across `Sleep`, `Activity`, `Readiness`,
  `SleepSession`.
- `ingest_advanced_data(before, after)` is true only when the newest local day moved
  forward.
- `apply_post_ingest_result` bumps `last_run` only when ingest advanced, and otherwise
  surfaces "Ingest finished but no new days were added. Request a fresh Oura export and
  sync again."
- There is currently **no record of which export was last ingested** (no checksum,
  manifest, per-file hash, or per-entity high-water mark). This is the central missing
  capability this spec must enable.

## 2. Problem statement

Reduce ingest time and redundant work when most of an export is already represented
locally, while keeping data correct (including Oura's corrections/backfills) and
keeping sync behavior understandable to users.

This is a **specification**, not an implementation design. Schema changes, storage
choices, and algorithms are explicitly out of scope; this document defines required
behavior, correctness guarantees, success criteria, and test coverage so the team can
choose an implementation.

## 3. Goals and non-goals

### Goals

- G1. Make a "nothing new" ingest (re-download of an export already fully ingested)
  fast — near-instant from the user's perspective.
- G2. Make an "N new days" ingest cost roughly proportional to N, not to total history.
- G3. Preserve correctness: corrections, backfills, and late-arriving rows from Oura
  must still land in the database.
- G4. Keep user-facing sync messaging accurate about whether new data was added,
  skipped, or re-processed.
- G5. Integrate cleanly with the existing "no new days → request a fresh export" flow.

### Non-goals

- N1. Changing how exports are requested/downloaded from Oura (Playwright flow).
- N2. Changing the analytics/read models that consume the database.
- N3. Switching away from SQLite or redesigning the schema for its own sake (a schema
  change may be *needed*, but redesign is not a goal).
- N4. Real-time / streaming ingest, or talking to Oura's API instead of the export ZIP.

## 4. Scope — entity types and files

The export contains roughly three tiers of data. Incremental/skip logic should be
prioritized by cost and safety.

### 4.1 In scope — high-frequency series (highest priority)

These are the largest files and the biggest time sink. They are append-mostly and
keyed by `timestamp`.

| File | Entity | Key | Notes |
| --- | --- | --- | --- |
| `heartrate.csv` | `HeartRate` | `timestamp` | Largest file; dominant cost. |
| `temperature.csv` | `Temperature` | `timestamp` | Large, append-mostly. |
| `ringbatterylevel.csv` | `RingBattery` | `timestamp` | Large, append-mostly. |

Rationale: these dominate ingest time, rarely change historically, and have a natural
time ordering that makes "only process rows newer than what we have" tractable.

### 4.2 In scope — daily summaries and sessions (medium priority)

Smaller per-row count but still re-processed fully today. Keyed by `day` or `id`.

| File(s) | Entity | Key |
| --- | --- | --- |
| `dailysleep.csv` (+ `sleeptime.csv`, `dailyspo2.csv`) | `Sleep` | `day` |
| `dailyactivity.csv` (+ `daytimestress.csv`) | `Activity` | `day` |
| `dailyreadiness.csv` (+ `dailystress.csv`) | `Readiness` | `day` |
| `dailyresilience.csv` | `Resilience` | `day` |
| `dailycardiovascularage.csv` | `CardiovascularAge` | `day` |
| `sleepmodel.csv` | `SleepSession` | `id` (large JSON sequences per row) |
| `workout.csv` | `Workout` | `id` |
| `session.csv` | `Meditation` | `id` |

Rationale: cheaper than high-frequency data, but `sleepmodel.csv` carries large JSON
sequences (`sleep_phase_30_sec`, `hr_data`, etc.) whose parsing is non-trivial, so it
benefits from skip logic. Daily summaries are the entities most prone to **Oura
corrections** (a score recomputed days later), so their skip logic must be more
conservative than high-frequency data (see §5).

### 4.3 In scope — small metadata (low priority, include for completeness)

| File | Entity | Key |
| --- | --- | --- |
| `ringconfiguration.csv` | `RingConfiguration` | `id` |
| `enhancedtag.csv` | `Tag` | `id` |

Rationale: tiny and cheap. Including them in any "whole-export skip" path keeps logic
uniform; per-file incremental logic is optional because the cost is negligible.

### 4.4 Explicit exclusions

- E1. **User-authored / mutable data** (e.g. tags/`enhancedtag.csv`, comments) must
  never be skipped based purely on "we already have this day." Tags can be edited or
  deleted by the user after the fact and are cheap to re-process. Always re-process or
  use content-level detection, never day-based high-water marks.
- E2. Any file **not currently mapped** by `parse_directory` stays out of scope; this
  spec does not add new entity types.
- E3. The **most recent local day(s)** must never be skipped on the assumption they are
  complete (see §5.3 "trailing-edge re-processing").

## 5. Correctness — detecting "already imported" vs "new or changed"

This is the heart of the spec. The implementation may combine several detection
mechanisms, but it must satisfy the following requirements regardless of mechanism.

### 5.1 Detection signals (solution space, not a mandate)

The team may use any combination of:

1. **Whole-export identity** — a hash/fingerprint of the downloaded ZIP or of each
   contained CSV. If the export (or a given file) is byte-identical to the last
   ingested one, that file's ingest can be skipped entirely.
2. **Per-file fingerprint** — size + modified-time + content hash per CSV, recorded
   after a successful ingest, so unchanged files are skipped even when other files
   changed.
3. **Per-entity high-water mark** — the maximum `timestamp` (high-frequency) or `day`
   (summaries) already stored, used to filter rows so only newer rows are parsed/upserted.
4. **Row-level content comparison** — for entities prone to correction, compare
   incoming row content against stored content and upsert only on difference.

The spec does not require a specific choice, but the chosen mechanism MUST meet the
correctness requirements below.

### 5.2 Correctness requirements (mandatory)

- C1. **No data loss.** Any row present in the export that is not represented (or is
  represented with different content) locally MUST be written. Skip logic may only
  skip work that is provably redundant.
- C2. **Corrections and backfills must land.** Oura recomputes scores and backfills
  earlier days. Detection MUST NOT assume "we have day D ⇒ day D is final." For
  correction-prone entities (daily summaries, sleep sessions), skipping based solely on
  key-presence is **not allowed**; detection must be content-aware (hash/compare) or
  must always re-process a trailing window (see §5.3).
- C3. **Partial / truncated exports must be safe.** If an export is missing files or
  has fewer rows than we already have (e.g. Oura returns a partial archive), ingest
  MUST NOT delete or regress existing data, and MUST NOT advance any high-water mark or
  fingerprint as if the partial export were complete. Skip logic must be additive only:
  it never removes local rows.
- C4. **High-water marks advance only on verified success.** Any persisted "last
  ingested" fingerprint or high-water mark may only be committed after the
  corresponding rows are committed to the database. A failed/rolled-back ingest must
  leave detection state unchanged so the next run re-attempts the same work.
- C5. **Idempotent.** Running ingest twice on the same export yields the same database
  state and the same "advanced / not advanced" outcome.
- C6. **Key semantics preserved.** Upserts continue to use existing natural keys
  (`day`, `id`, `timestamp`). Incremental logic changes *what we read/compare*, not the
  uniqueness contract.

### 5.3 Trailing-edge re-processing (mandatory safeguard)

The newest day(s) in an export are the most likely to change between exports (Oura
finalizes sleep/readiness/activity scores and may add late HR samples). Therefore:

- T1. Define a **re-process window** `W` (number of trailing days, configurable;
  suggested default 2–3 days). Data within the last `W` days of the local
  `latest_day` (or the export's latest day) MUST always be re-evaluated for changes,
  even if a high-water mark says we "have" it.
- T2. Skip logic for older-than-`W` data may rely on cheaper signals (file/export
  fingerprint, high-water mark).
- T3. The window `W` must be documented and, ideally, adjustable without a code change
  (config value) so it can be tuned if Oura's correction behavior changes.

### 5.4 Handling "no fingerprint yet" (first run / migration)

- F1. If no detection state exists (fresh install, or upgrade from a version without
  this feature), ingest MUST fall back to the current full-ingest behavior and then
  record detection state. The first ingest after upgrade is allowed to be slow.

### 5.5 Stable identity for generated-key entities (mandatory design fix)

Incremental detection compares incoming rows against stored rows by key and/or by
content. The current code makes both unreliable for several entities because keys are
**non-deterministic across exports**. This MUST be fixed before any skip/compare logic
can be trusted.

**The concrete problem in today's code:**

- These entities upsert on `id` but mint a fresh `uuid.uuid4()` whenever Oura's CSV row
  lacks an `id`, so the "same" row gets a different key on every export:
  - `SleepSession` (`sleepmodel.csv`, `_upsert(SleepSession, records, ['id'])`)
  - `Workout` (`workout.csv`, `_upsert(Workout, records, ['id'])`)
  - `Meditation` (`session.csv`, `_upsert(Meditation, records, ['id'])`)
  - `Tag` (`enhancedtag.csv`, `_upsert(Tag, records, ['id'])`)
  - `RingConfiguration` (`ringconfiguration.csv`, `_upsert(RingConfiguration, …, ['id'])`)
  - The shared `_read_csv_robust` also auto-inserts `str(uuid.uuid4())` when a header
    expects `id` but the row omits it.
- Day-keyed entities (`Sleep`, `Activity`, `Readiness`, `Resilience`,
  `CardiovascularAge`) conflict on `day`, but `_upsert` builds its update set as *all
  columns except the conflict key*, so the generated `id` primary key is **rewritten
  with a new UUID on every ingest**. The row's business content is identical but its
  `id` churns each run.

**Why it breaks incremental ingest:**

- For `id`-conflict entities, a random key never matches the prior run, so skip-by-key
  is impossible and naive logic risks duplicate inserts.
- For any content-hash comparison, including the volatile `id` makes every row look
  "changed" on every export, defeating "nothing changed" detection.

**Required design fix:**

1. **Deterministic synthetic key.** When Oura omits a stable `id`, derive the key
   deterministically from the row's natural identifying fields instead of
   `uuid.uuid4()`. Use a fixed field order and a stable hash (e.g. SHA-256 of normalized
   values), so the same business row always yields the same key across exports.
   Suggested natural-key fields per entity:
   - `SleepSession`: (`day`, `bedtime_start`, `type`)
   - `Workout`: (`day`, `start_time`, `activity`)
   - `Meditation`: (`day`, `start_time`, `type`)
   - `Tag`: (`start_time`, `tag_type_code`, `comment`)
   - `RingConfiguration`: (`firmware_version`, `hardware_type`, `color`, `size`)
   When Oura *does* provide an `id`, keep using it.
2. **Stop PK churn on day-keyed entities.** Exclude the generated `id` column from the
   conflict update set for `day`-keyed entities (or generate that `id` deterministically
   too) so re-ingesting an unchanged day does not rewrite the primary key. Without this,
   "unchanged export" still mutates rows and defeats §8 M1.
3. **Exclude volatile columns from content comparison.** Any change-detection hash MUST
   exclude (a) identity columns and (b) ingest-time-derived fields (e.g. re-formatted
   timestamps, regenerated keys). Comparison operates only on normalized business
   fields, so a re-derived key or reparsed timestamp never registers as a change.
4. **Tags remain re-processed, not skipped.** The deterministic key for `Tag` only
   prevents duplicate rows; per §4.4 E1, tags are user-editable and must still be
   re-evaluated for content changes (and deletions handled per existing semantics),
   never skipped on key-presence alone.

**Migration consequence:** rows already stored under random UUIDs will not match the
new deterministic keys, so the first ingest after this change could insert
deterministic-keyed duplicates of existing rows. The rollout MUST include a one-time
normalization/dedup (or a full re-ingest via the §11 escape hatch). See §11 O7.

## 6. User-visible behavior

Sync status is surfaced through `config_manager.update_status` (message + status) and
the shared `SyncFreshness` read model used by desktop and Android. Behavior must remain
truthful about what happened.

### 6.1 Status messaging requirements

- U1. When an export is downloaded that is **identical** to the last ingested one and
  nothing is processed, the user-facing message MUST make clear that no new data was
  found and that this is expected/fast — not an error. It should reuse / align with the
  existing "no new days were added — request a fresh Oura export and sync again"
  guidance rather than implying success with fresh data.
- U2. When `N` new days (or new high-frequency rows) are added, messaging MUST reflect
  that new data landed, consistent with today's "advanced" path that bumps `last_run`.
- U3. When only **corrections** (no new latest day, but changed older rows) are applied,
  messaging MUST NOT claim "no changes." It should communicate that existing days were
  updated even though `latest_day` did not advance. (This is a behavior change from the
  current binary advanced/not-advanced model and must be designed for.)
- U4. Progress indication during ingest should distinguish "checking what's new" from
  "importing N days / files" so a fast skip does not look like a stall or a failure.
- U5. The `advanced` return value contract (`ingest_zip_async` returns whether the
  newest local day moved forward) MUST be preserved for callers that branch on it
  (e.g. the fresh-export decision in `run_full_sync_task`), OR those callers must be
  updated in lockstep. Changing `advanced` semantics silently is prohibited.

### 6.2 Freshness read model

- U6. `last_ingest_at` / `last_run` semantics: keep the current rule that "last ingest"
  implies fresh data only when the latest day advanced. If U3 (corrections-only)
  updates are introduced, define explicitly whether a corrections-only run counts as a
  "successful ingest" for the freshness badge. Recommended: it counts as a successful
  ingest (data changed) but does not change the "days behind" lag computation.

## 7. Interaction with the sync flow

The full-sync orchestration (`run_full_sync_task`) currently:

1. Downloads any export already ready on Oura.
2. Ingests it.
3. If ingest did **not** advance the latest day, requests a **fresh** export
   (`skip_ready_download=True`) and ingests that.

Incremental ingest must compose with this without regressions:

- S1. The "did this ingest advance?" decision that drives requesting a fresh export
  MUST remain correct. A fast skip of an identical export MUST still report
  "not advanced" so the fresh-export request still fires. (A skip must not be mistaken
  for success.)
- S2. After a fresh export is downloaded, if it is **also** identical to what we have
  (Oura returned the same snapshot), the system must avoid an infinite request loop.
  Define a stop condition: e.g. do not request more than one fresh export per
  user-initiated sync, and surface "Oura has not produced newer data yet" rather than
  looping. (This bound should exist today via the single fresh-export request; the spec
  must preserve it.)
- S3. The fingerprint of "last ingested export" should help short-circuit the
  download→ingest→detect cycle: if the freshly downloaded ZIP fingerprint equals the
  last ingested one, we can skip parsing entirely and go straight to the "no new data,
  request fresh / give up" branch.
- S4. `last_export_request_at` and stuck-sync recovery (`sync_recovery.py`,
  `STUCK_AFTER = 20 min`) must continue to work. Because incremental ingest is faster,
  fewer runs should ever approach the stuck threshold; verify the recovery path still
  triggers for genuinely stuck *download* phases.

## 8. Success criteria (measurable)

Measured on a representative database with multi-year history (large `heartrate.csv`,
`temperature.csv`, `sleepmodel.csv`). Baseline = current full ingest (~5 min reported).

- M1. **Unchanged export (`latest_day` does not advance, no corrections):** end-to-end
  ingest (parse + detect + commit, excluding download) completes in **≤ 5 seconds**,
  and ideally < 2 s. Target: ≥ 95% reduction vs baseline.
- M2. **One new day added:** ingest completes in **≤ 15 seconds**. More generally,
  ingest time should scale ~linearly with new days/rows, not with total history.
- M3. **N new days added:** ingest time ≈ `fixed_overhead + k·N`, with `fixed_overhead`
  on the order of M1 and `k` small enough that a typical catch-up (e.g. 7 days) stays
  well under the baseline.
- M4. **Corrections-only export (older days changed, no new latest day):** detection +
  re-import of changed rows completes in **≤ 30 seconds** (bounded by the trailing
  window `W` plus any content-changed older rows).
- M5. **First run after upgrade (no detection state):** may match baseline; no
  regression beyond current full ingest time.
- M6. **Correctness, not just speed:** for each scenario, a full re-ingest from scratch
  on the same export produces a byte-identical database (modulo non-deterministic
  fields), proving skip logic dropped no data.

Targets are directional; exact thresholds can be tuned during review but the
*relationships* (M1 ≪ M2 ≪ baseline; time ∝ new data) are the binding criteria.

## 9. Risks and edge cases

- R1. **Over-aggressive skipping drops corrections.** Mitigated by §5.2 C2 and the
  trailing-edge window §5.3. Do NOT optimize away re-processing of recent days or
  content-changed rows.
- R2. **Partial / truncated export looks "older" than local.** Must be treated as
  partial, never as authoritative; never delete or regress, never advance fingerprints
  (§5.2 C3).
- R3. **Stale fingerprint after manual DB edits / restore.** If the database is
  replaced or rolled back out of band, a stored high-water mark could be ahead of
  actual data and cause under-import. Mitigation: prefer content/fingerprint signals
  that can be re-derived from the DB, or provide a "force full re-ingest" escape hatch
  (see §11 R3).
- R4. **Non-deterministic IDs.** `_read_csv_robust` and processors generate UUIDs when
  `id` is missing (e.g. `str(uuid.uuid4())`), and `_upsert` rewrites the generated `id`
  PK of day-keyed entities on every run. Without a fix, content/key comparison never
  matches across runs, causing duplicate inserts or perpetual "changed" detection. This
  is addressed by the mandatory design fix in **§5.5** (deterministic synthetic keys,
  no PK churn, volatile columns excluded from comparison); the migration/dedup
  consequence is handled in §11 O7. Tags remain re-processed, not skipped (§4.4 E1).
- R5. **Timezone / timestamp parsing drift.** High-frequency high-water marks rely on
  consistent `timestamp` parsing (`_parse_datetime`, ISO8601). Inconsistent parsing
  between runs could skip or duplicate boundary rows. Comparisons must use parsed,
  normalized timestamps.
- R6. **Clock/order assumptions.** Do not assume the export's rows are sorted; a
  high-water-mark filter must handle unsorted input (scan, not early-exit) unless
  ordering is verified.
- R7. **Schema/JSON sequence changes.** `sleepmodel.csv` sequence fields are large and
  occasionally re-encoded by Oura; a row may be "the same day" but with materially
  different sequence content. Treat content change as a real update.
- R8. **Concurrency.** Ingest runs in a worker thread off the event loop; detection
  state writes must be transactionally consistent with row writes (§5.2 C4) to avoid a
  crash leaving fingerprints ahead of data.
- R9. **Things we must NOT optimize away:** trailing-window re-processing; the
  fresh-export request when nothing advanced; correctness re-checks for daily summaries
  and sleep sessions; user-authored tag re-processing.

## 10. Testing strategy

All scenarios assume a seeded database and crafted export fixtures.

### 10.1 Functional / correctness tests (must pass before ship)

- TC1. **Identical re-ingest is a no-op.** Ingest export X twice; second run writes no
  new rows, reports "not advanced," and DB is unchanged.
- TC2. **One new day.** Export X+1 day; only the new day's rows are written; older rows
  untouched; reports "advanced."
- TC3. **N new days.** Same as TC2 for N days; verify all N land.
- TC4. **Correction to an existing day.** Export where an older day's score/sequence
  changed; verify the changed row is updated even though `latest_day` did not advance;
  verify messaging reflects an update (U3).
- TC5. **Backfill of an older missing day.** Export adds a day older than current
  `latest_day`; verify it is inserted (high-water mark on `latest_day` must not hide it).
- TC6. **Partial export.** Export missing files / fewer rows than local; verify no
  deletion, no regression, no fingerprint/high-water advance (C3).
- TC7. **Trailing-window correction within W.** A change inside the last `W` days is
  always detected even with fingerprints "matching."
- TC8. **Generated-key entities (§5.5).** For `SleepSession`/`Workout`/`Meditation`/
  `Tag`/`RingConfiguration` rows lacking an Oura `id`, re-ingesting the same export
  produces the **same** deterministic key (no duplicate rows) and is detected as
  "unchanged." Verify a day-keyed entity's `id` PK is stable across re-ingest (no PK
  churn). Verify the pre-fix migration/dedup (O7) collapses old random-UUID rows.
- TC9. **Crash/rollback mid-ingest.** Simulate failure after partial write; verify
  detection state did not advance and a re-run completes correctly (C4, R8).
- TC10. **First run with no detection state** falls back to full ingest and records
  state (F1).
- TC11. **Equivalence check.** For TC1–TC7, a from-scratch full ingest of the same
  export yields the same DB as the incremental path (M6).

### 10.2 Performance tests

- TP1. Measure ingest time for: unchanged export, +1 day, +7 days, corrections-only,
  cold first run — on a large fixture. Assert against §8 targets (with margin for CI
  variance).
- TP2. Confirm time scales with new-data size, not total history (compare small vs
  large fixture for the same "+1 day" delta).

### 10.3 Integration / flow tests

- TI1. `run_full_sync_task`: unchanged ready export → still triggers fresh-export
  request (S1); fresh export also unchanged → terminates without looping (S2).
- TI2. `SyncFreshness` / status messages reflect skip vs new vs corrections (§6).
- TI3. Existing ingest tests (`test_ingest_runner.py`, `test_sync_freshness.py`,
  `test_action_cards.py`) continue to pass or are updated intentionally.

## 11. Rollout

- O1. **Schema/migration.** If detection state requires persistence (fingerprints,
  high-water marks, per-file hashes), it likely needs a small new table or config
  store. Treat as additive: new table/columns only, with a forward migration that does
  not touch existing data. SQLite migration must be safe on existing user databases.
- O2. **One-time backfill.** No historical data backfill is required: detection state is
  derived from the DB and/or recorded on the next ingest. The first post-upgrade ingest
  is a full ingest that seeds detection state (F1, M5). Document this expected one-time
  slow run.
- O3. **Feature flag.** Ship behind a config flag (default decided at review;
  recommended **on** after the equivalence tests TC11 pass) so it can be disabled if a
  correctness issue is found in the field, reverting to full ingest.
- O4. **Escape hatch / force full re-ingest.** Provide a user- or support-triggerable
  "re-import everything" that clears detection state and runs a full ingest, for
  recovery from R3-style state corruption. This must exist before enabling skipping by
  default.
- O5. **Observability.** Log per-run: files skipped vs processed, rows processed per
  entity, detection mechanism outcome, and total ingest duration, so we can verify the
  success criteria in real usage and debug field reports.
- O6. **Reversibility.** Disabling the flag must immediately restore current behavior
  with no data fix-up required (detection state is ignored, not destructive).
- O7. **One-time key normalization/dedup (§5.5).** Switching generated-UUID entities to
  deterministic synthetic keys means existing random-UUID rows will not match new keys.
  Ship a one-time, idempotent migration that recomputes deterministic keys for affected
  entities (`SleepSession`, `Workout`, `Meditation`, `Tag`, `RingConfiguration`) and
  collapses duplicates, OR require a one-time full re-ingest via the O4 escape hatch.
  This migration MUST run before (or as part of) enabling skip logic so detection is
  not built on stale random keys. Verify it is safe to re-run.

## 12. Open questions (resolve during review)

- Q1. Exact trailing-window `W` default (2 vs 3 days) and whether it differs per entity
  (e.g. sleep finalizes later than activity).
- Q2. Should corrections-only runs count as `advanced` for `last_run`/freshness (see U6
  recommendation)?
- Q3. Detection granularity: whole-ZIP hash vs per-file hash vs per-entity high-water
  mark — chosen at implementation time against the §8 targets, but reviewers should
  agree on the minimum acceptable mechanism for correction-prone entities.
- Q4. Where detection state lives (new SQLite table vs `config`), given O1/O6.
