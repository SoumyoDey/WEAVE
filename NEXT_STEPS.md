# Next steps

State as of 2026-08-14. Branch `p0-reliability`, PR #2 on `SoumyoDey/WEAVE`.

## Where things stand

PR #2 is **open, MERGEABLE, CLEAN, and deliberately not merged** — 51 commits,
30 files, +9219/−1332. `main` has not moved, so it is a clean fast-forward.

- 174 backend + 22 frontend tests pass. `metrics.py` at 100% statement coverage.
- No reviews, and no CI on the repo (`checks: 0`) — nothing runs on merge.
- `METRICS_AUDIT.md` is the record for everything below. Read it before
  re-deriving anything; several conclusions in it were reached, withdrawn and
  re-established, and the reasoning for each is kept.

---

## 1. Merge PR #2

Blocked only on review. It changes every precipitation number in the app, so it
is worth a second pair of eyes — particularly `Data/metrics.py`, where the unit
and window conventions live.

```bash
gh pr merge 2 --repo SoumyoDey/WEAVE --squash --delete-branch
```

`--squash` given 51 commits, many iterating on one finding. Use `--merge` instead
if the individual messages are worth keeping — they carry most of the reasoning.

## 2. Drop the superseded table

Quick and safe. Nothing reads `regridded_forecast` any more (only comments
mention it); it is 245 MB superseded by `regridded_forecast_ens`, which carries a
true ensemble spread derived from `regridded_forecast_member`. It was kept only
so the old and new numbers could be compared, and that comparison is done and
written up.

```sql
DROP TABLE regridded_forecast;
```

Grep for the name first, in case something new started reading it.

## 3. A fixture-database test layer  ← the one that matters

`metrics.py` is at 100%, but `flask_api.py` is at **41%**. The untested 59% is
the SQL and the Cartopy rendering — which is exactly where this audit kept
finding bugs.

Every correctness fix in this PR was caught by hand-querying the database, not by
a test. Findings 12, 16 and 17 were all invisible to a green suite. Without a
fixture DB the guarantee is "someone looked hard, once", which does not survive
the next ingest or the next person.

Shape: a small Postgres fixture (schema + a few hundred rows spanning all three
models and both variables), loaded once per session, with the endpoints exercised
against it. `Data/test_endpoints.py`'s `RoutedCursor` already covers the contract
layer; this is for everything that depends on real SQL semantics.

## 4. Surface observation coverage in the UI

Truth exists only to fh ≈ 19.5 for the loaded run. Beyond that, verification
correctly returns nothing with a warning — but a user scrubbing to +48 h sees an
empty panel and cannot tell that from a bug. Show the observation record's extent
somewhere in the interface.

## 5. Lower priority

- **Vite migration** — CRA is EOL.
- **Cache the deterministic metric endpoints** — only the plot endpoint is cached.
- **Row caps on point-list queries** — currently unbounded.

---

## Standing decisions — do not undo these by accident

**GEFS precipitation will not be re-exported.** The correction in
`SCALED_EXPORT_DIVISOR_HOURS = {'AIFS': 6.0, 'GEFS': 3.0}` is therefore
permanent. It is not debt: it describes how the loaded data was produced.

If that ever changes and `Data_convert_weave/"aifs react.py"` is re-run (it has
been fixed to divide by each record's own window), the constant must move to
`{'AIFS': 6.0, 'GEFS': 6.0}` **in the same change**, or the correction applies
twice. `/api/health` now infers the convention from the data and reports
`ok` / `MISMATCH` / `indeterminate`, so forgetting is caught rather than silent.

**Every model is verified over a common 6-hour window**
(`COMMON_VERIFICATION_WINDOW_HOURS`). Display paths keep native cadence on
purpose. Wind is exempt — instantaneous, so there is no window to reconcile.

**The GEFS filenames lie.** Every file is named
`Total_precipitation_surface_3_Hour_Accumulation_ens_*`, including the `f006`,
`f012`, `f018`, `f024` files that hold **6-hour** totals. Read `step` from the
file, never the name. Verified on two independent runs.

## Method lessons, earned the hard way

Three findings in this audit were wrong and had to be withdrawn. All three failed
the same way — a real signal, misread as to cause.

1. **Never raw Pearson on a skewed field.** It retracted finding 15 entirely.
   Use Spearman, or Pearson on `log1p`, or a categorical score.
2. **Always control against a known-good pair.** Run the same statistic on
   model-vs-model before concluding anything about data quality.
3. **Model-vs-model agreement is not a truth test.** Ensembles share initial
   conditions and physics lineage, so they agree with each other more than with
   an independent reanalysis. That is expected, not diagnostic.
4. **Do not infer a constant from a filename.** The `_scaled` folder name led to
   a guessed divisor of 6; the actual script said 3, which inverted the fix.

The pattern throughout: a fingerprint in the data reliably shows *that* something
is wrong, and reliably cannot say *which* explanation produced it. Three raw
files settled in minutes what a week of correlation tests could not. When a
source of truth exists, go and read it.
