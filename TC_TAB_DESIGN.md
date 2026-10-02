# Design — the tropical cyclone tab

**Status: proposed, 2026-10-02. Nothing built.**

Step 3 of `NEXT_STEPS.md` §37. Step 1 is done and is the foundation for all of
this: `TC_DATA_ACCESS.md` says what the data actually is, measured rather than
assumed, and every number below comes from there.

This document decides what can be decided from the files, and names the rest as
decisions with an owner. It does not decide the one thing that matters most,
because that one belongs to whoever asked for the feature — see §2.

---

## 1. The goal, restated

Both requested features ask the same question: **do the ensemble members
agree?** Feature 1 asks it about *where the storm goes*; feature 2 about *what
the storm does*.

That is the question this application already exists to answer. Its metric
vocabulary — spread-skill ratio, spread-error correlation, CRPS — is entirely
about whether an ensemble's disagreement matches its error. So a cyclone tab is
an extension of the existing idea, not a visitor in the same window, and the
design should make that visible rather than building a second, unrelated app
behind a fourth tab.

**What the data adds that the app does not have: sample size.** Today's
verification rests on one or two initialisations, which is why every statement
about relative model skill here is hedged. The track archive holds **138 storms
across 12 years**. That is a different statistical footing, and it is arguably
worth more than either requested visualisation.

---

## 2. Feature 2 — DECIDED 2026-10-02: a field derived from the tracks

**"Render all individual model runs as semi-transparent layers at once" has
three readings, and they differ by two orders of magnitude in cost.**

| reading | data needed | status |
|---|---|---|
| **(a)** member *gridded fields* per storm | a fresh TIGGE field ingest | **no data exists** |
| **(b)** member *tracks* as translucent lines | `output/` | this is feature 1 |
| **(c)** a *field derived from the tracks* — strike probability, track density, an ensemble cone | `output/` | **buildable now** |

`/projects/k.aggarwal/Shuochen` contains 71,865 XML, 3,243 CSV and exactly one
NetCDF — and that NetCDF is IBTrACS. **There are no forecast fields for these
storms anywhere in it.** Reading (a) is a new data acquisition, and for scale
the existing three-model single-run load is 55 GB against §27's 250 GB review
threshold.

**(c) is chosen** — decided 2026-10-02. It is a genuine translucent layer, it
answers "do the scenarios cluster or diverge" more directly than fifty
overplotted polylines, it is the standard operational idiom, and it computes
from 197 MB already on disk. (a) and (c) look nearly identical in a mockup and
differ enormously in cost, which is why the choice was worth making deliberately
rather than discovering halfway through.

§6a specifies it. (a) is not refused, only deferred: if member rasters are
wanted later, the decoupling below is how to find out whether they are worth the
ingest.

### A decoupling worth taking either way

The app **already holds per-member gridded fields** — `regridded_forecast_member`
for 2025-09-08 and 09-16. If (a) is what is wanted, the *rendering* problem can
be prototyped on that today, with no cyclone data at all. That separates the
hard question (fifty translucent layers, ~84,000 points per lead time) from the
expensive one (a new ingest), and answers whether the visualisation earns its
keep before anyone pays for the data.

---

## 3. What is new, and what is reused

**New, because a track is not a grid.** Everything in this app is
`(model, variable, init_time, forecast_hour, lat, lon, value)` on a 0.5° lattice.
A track is an ordered polyline per member with intensity attributes. It needs its
own tables and its own endpoints.

**Reused, because the conventions were expensive to establish:**

- the **registry pattern**. `forecast_run_registry` exists because what was
  loaded must be *recorded*, not inferred from the rows present (§13). The
  cyclone data needs this more acutely — see §5.
- the **`--compare` discipline** from `regrid_observations.py`: when a stored
  value can be recomputed, recompute it and measure the difference rather than
  trusting it.
- the **spread-versus-error vocabulary**, which transfers directly (§6).
- the **units honesty** that `fixture_db.py` documents: restate a convention
  where it is used, never import it from the code under test.

---

## 4. Data model

Three tables. The split matters: the source CSVs repeat the best track and the
ensemble mean on **every member row**, which is 51× redundant and makes the
observed track a property of a forecast rather than of the world.

### `cyclone_track_member` — the forecast

```
centre          TEXT      -- 'ecmf' | 'egrr' | 'kwbc'  (the distributing node)
system          TEXT      -- 'ECMWF-ENS' | 'MOGREPS' | 'GEFS'  (the actual model)
storm_id        TEXT      -- IBTrACS SID, not the name: names repeat across basins and years
init_time       TIMESTAMP -- the initialisation, UTC
member_id       INTEGER
lead_hours      INTEGER
valid_time      TIMESTAMP
latitude        REAL      -- signed ±180 / ±90, normalised on load
longitude       REAL
pressure_hpa    REAL
wind_ms         REAL
```

**`system` is separate from `centre` deliberately.** `kwbc/` is a distribution
node carrying NCEP *and* Canadian products; `output/` uses NCEP GEFS, but the
raw archive does not, and a schema that conflates the two re-creates the §20/§24
mislabel at the storage layer.

**`storm_id` is the IBTrACS SID.** Storm *names* are reused — there is a MICHAEL
in several basins and several years — and `output/` filenames carry only the
name. `KYAAR_KYARR` also contains an underscore, so the filename cannot be
parsed on `_` at all. The SID is in the CSV; use it.

### `cyclone_best_track` — the truth

```
storm_id, valid_time, latitude, longitude, nature,
wmo_pressure, wmo_wind, dist_to_land_km, landfall_km, storm_speed, storm_dir
ibtracs_version TEXT  -- see §7: which download this came from
```

One row per storm per time, not per member.

### `cyclone_run_registry` — what was loaded, and how big the ensemble *should* be

```
centre, system, storm_id, init_time,
nominal_members INTEGER,   -- what the system runs: 51, 36, 31, 21
tracked_members INTEGER,   -- how many produced a track for this storm
init_offset_h   INTEGER,   -- the 0/24/48/72 grouping in the source filenames
source_generation TEXT,    -- 'output-2026-06' | 'staged-2026-04'
ibtracs_version   TEXT
```

**This table is the most important one and the least obvious.** §5 says why.

---

## 5. The denominator problem

ECMWF is 51 members. `output/` carries storms at 50, 49, 48, 47, 46, 45, 44, 42
and one at **28**. Nothing changed about the ensemble — **those members forecast
no cyclone, so the tracker emitted nothing for them.**

So the member count *cannot be derived from the data present*. It has to be
recorded, which is precisely the argument `forecast_run_registry` was built on.

**And it is not a bookkeeping detail — it is the most interesting number on the
chart.** "28 of 51 members tracked this storm" means twenty-three members
predicted no cyclone at all. Drawing 28 tracks and letting a reader take that
for the ensemble understates the spread of outcomes in the direction that
matters most: whether the storm happens.

`nominal_members` is per `(system, init_time)` because **GEFS changed size
mid-archive** — 21 members before v12 on 2020-09-23, 31 after. A constant would
be wrong for half the record.

**The UI must show the denominator.** "28 / 51 members" beside the map, not in a
tooltip.

---

## 6. What the tab shows

Five views, and only the first and last are new vocabulary:

1. **The spaghetti map.** Every member's track as a polyline, the best track
   over it, the ensemble mean distinct. With the denominator stated.
2. **Track error against lead time** — the existing metric-versus-lead chart
   idiom, with `distance_km` in place of MAE. Monotone growth is also the
   provenance test (§7).
3. **Spread against error** — `dist_to_ens_mean_km` against `distance_km`. This
   *is* the spread-skill relationship the app already computes for
   precipitation and wind, in track space. Same question, same reading, new
   quantity.
4. **Centres compared** — ECMWF against MOGREPS against GEFS on one storm, which
   is the Comparison tab's existing shape.

5. **Strike probability** — feature 2, a server-side derived field on the
   analysis grid, rendered through the existing overlay. Specified in §6a.

### Scale: there isn't a problem

51 members × 25 lead times = **1,275 points** for a storm-centre-offset, perhaps
50 KB of JSON. For comparison, one lead time of one gridded variable for 50
members is ~84,000 points, which is why `POINT_LIST_MAX_CELLS` exists.

**Feature 1 needs no cap, no tiling and no binary format.** Say so plainly, so
nobody imports the point-list machinery for a payload two orders of magnitude
smaller than the thing it was built for.

---

## 6a. Feature 2, specified: strike probability

**The field.** For each cell of the analysis grid, the fraction of the ensemble
whose track passes within **R** kilometres of that cell at any lead time in the
selected window:

```
strike_probability(cell) = members_whose_track_comes_within_R(cell) / nominal_members
```

Dimensionless, in [0, 1], one value per cell — **the same shape as every other
field this app renders.** That is the point of choosing it: it goes through
`_render_metric_map_png` and the browser canvas overlay unchanged, and through
the existing legend machinery as a dimensionless metric with no wind variant,
exactly like CSI or POD.

### The denominator is `nominal_members`, and this is not a detail

A member that forecast no cyclone contributes a **"no strike"**, not an absence.
Dividing by `tracked_members` instead would be wrong by a factor of up to
**51/28 ≈ 1.8** on the storms where it matters most — the ones where the
ensemble disagreed about whether there would be a storm at all.

That is the same shape of error as the export-divisor defect (§13, §22): a
plausible number, silently wrong by a constant, with nothing downstream able to
tell. §5 is why the registry carries `nominal_members`; this is what it is for.

**A test must pin it**: a synthetic ensemble where half the members have no
track must produce a maximum probability of 0.5, not 1.0.

### R is a parameter, and it is exposed

The radius changes the answer, so it is a control and not a constant. This is
the pattern the app already has: `requires_threshold` metrics put their
threshold in the panel, and `/api/config` declares which ones need it. Strike
probability is the same shape — a dimensionless field whose value depends on a
stated parameter.

Default **120 km**, the usual operational choice, stated in the UI beside the
value rather than buried. The lead window reuses the existing `hour_min` /
`hour_max` vocabulary the comparison endpoints already take.

### Grid

The existing **0.5° analysis lattice**, which over the North Atlantic domain is
1,681 cells — measured, not estimated. At ~55 km, a cell is comfortably smaller
than the default radius, so the field is smooth rather than pixellated, and
reusing the lattice is what lets the whole render path be reused.

If the tab later covers basins outside the current extent, the lattice extends
with the extent (§9); the metric does not change.

### Endpoint

```
GET /api/cyclone/strike-probability
      ?storm=<SID>&centre=<c>&init=<t>&radius_km=120&hour_min=0&hour_max=144
   -> {points: [{lat, lon, value}], nominal_members, tracked_members, radius_km}
```

Same response shape as `/api/spatial-metric`, so the canvas overlay needs no new
case. **It returns both member counts**, because a probability without its
denominator cannot be checked by the person reading it.

1,681 cells is ~80 KB of JSON. No cap, no tiling, no binary format — see §6.

### What a test should assert, beyond the arithmetic

The invariants are cheap and they catch real mistakes:

- every value in [0, 1];
- **R → very large ⇒ every cell → 1.0**, and only if every member has a track;
- **R → very small ⇒ non-zero only at cells a track actually passes through**;
- a **tightly clustered** synthetic ensemble gives a narrow high-probability
  core; a **diverging** one gives a broad low-probability spread. This is the
  thing the feature exists to show, so it is the thing to assert — a field that
  could not tell those two cases apart would render beautifully and mean
  nothing.

The last is the lesson from §31's binning scene: construct the case the metric
is named for and prove the metric detects it, rather than checking it runs.

---

## 7. Verify the derived columns rather than importing them

`output/` ships `distance_km`, `mean_lat`, `mean_lon` and `dist_to_ens_mean_km`
already computed. **It also ships every input to them.** So they can be
recomputed and compared — and this project's standing position is that a number
whose derivation is unknown is not a measurement.

On load, recompute and report the difference, exactly as
`regrid_observations.py --compare` does:

- `distance_km` from the forecast position and the best track at the same valid
  time. A great-circle/haversine difference, a units error, or a nearest-time
  versus interpolated match would all show up here and nowhere else.
- `mean_lat`/`mean_lon` across members. **Note the trap:** a mean of longitudes
  across the dateline is wrong unless computed as a circular mean. If their
  value and ours disagree only for storms near 180°, that is the cause, and it
  is worth knowing which of the two is right.

**Run 2026-10-02 (`Data/compare_cyclone_derived.py`), and the trap was real.**

| column | verdict |
|---|---|
| `distance_km` | **reproduced exactly** — haversine, R = 6371.0 km, median \|diff\| 2×10⁻¹³ km |
| `mean_lat` | reproduced exactly |
| `mean_lon` | **arithmetic, not circular** — matches theirs to 0° everywhere, including across the antimeridian |
| `dist_to_ens_mean_km` | follows `mean_lon`, so wrong wherever it is |

So `distance_km` can be trusted and we now know precisely why. **`mean_lon` and
`dist_to_ens_mean_km` cannot**, for storms whose members straddle ±180°: the
arithmetic mean of +179 and −179 is 0, the wrong side of the planet. Measured
against a circular mean on the affected rows — median **65°**, max **213°** of
longitude, which carries `dist_to_ens_mean_km` to a maximum difference of
**16,309 km**.

**63 of 1,181 files, 15 storms**: BOLAVEN, DONNA, DORA, FENGSHEN, GITA,
HAGIBIS, HALONG, HAROLD, HECTOR, KEVIN, NIRAN, TRAMI, ULA, WINSTON, YASA.

This is why §7 exists and why the loader does not import these four columns.
Recomputing the ensemble mean ourselves, circularly, costs nothing; adopting
theirs would have put the mean track of fifteen Pacific storms in the wrong
ocean, and nothing downstream would have said so.

There is also a column `T` whose meaning nobody has established. **Do not load a
column nobody can name.**

**The provenance test**, the track analogue of §24's MAE-against-lead: track
error must grow monotonically with lead. A flat curve means the forecast is not
paired with its own valid times.

**Run 2026-10-02 over all 400 `0h` files — GATE PASSED.**
`compare_cyclone_derived.py --provenance`, Spearman rather than Pearson because
the question is whether error *rises*, not whether it rises linearly:

| centre | rho | +0 h | +144 h | growth |
|---|---|---|---|---|
| `ecmf` | **+1.0000** | 55.2 km | 558.4 km | 84 km/day |
| `egrr` | **+1.0000** | 71.9 km | 659.8 km | 98 km/day |
| `kwbc` | **+1.0000** | 40.2 km | 610.3 km | 95 km/day |

Perfectly monotone for all three. **And the magnitudes are independently
plausible**, which matters as much as the shape: ~250 km at day 3 and
550–660 km at day 6 is where published tropical-cyclone track verification sits,
and ECMWF leading at long lead is the known result. A fabricated or mispaired
set would have had to reproduce that by accident.

Two of 400 storm-centre pairs fell below rho 0.5 — LESTER and GAEMI, both
MOGREPS. **Looked at rather than waved through: neither is a defect.** Both
still rise overall, both are clean at another centre (kwbc/GAEMI runs
35 → 540 km, textbook), and `egrr`/LESTER is scored on 24 of 36 members, the
subset that tracked the storm at all. A single storm's curve has no reason to be
monotone. The per-storm check is therefore a flag, not a gate; the wording in
the script was corrected to say so.

---

## 8. Normalisation, decided from the files

| what | source state | on load |
|---|---|---|
| longitude | `ecmf` signed ±180; `egrr` positive magnitude + `units` carries the sign; `kwbc` 0–360 | **signed ±180**, and a test per centre with a western-hemisphere value |
| basin | `North Atlantic` (ECMWF) vs `AL` (NCEP) | one controlled vocabulary, mapping table, test |
| storm identity | name in the filename, SID in the file | **SID**; never parse the filename on `_` |
| times | `output/` is `YYYY-MM-DD HH:MM:SS` | UTC, stated |

The longitude row is the one to be careful about. Reading `egrr`'s value without
its `units` attribute puts a storm in the wrong hemisphere: one file carries
`units="deg W">103.0<` and `units="deg E">100.2<`, three apart as numbers and
**203 degrees apart on the Earth**. `TC_DATA_ACCESS.md` records that I got this
wrong twice before measuring it per centre.

---

## 9. Scope boundaries

- **Its own time axis.** The archive is 2013–2024; the loaded forecast runs are
  2025-09-08 and 09-16. **No overlap at all**, so the cyclone tab cannot share
  the run selector or `init_time` scoping, and should not try.
- **Its own models.** `ecmf` is ECMWF's physics ensemble, *not* AIFS. `egrr` is
  MOGREPS. Presenting them under the existing model names would be the §20/§24
  mislabel.
- **The domain is hardcoded** at ~24–46 N, −86 to −64 W, and tracks are global.
  Either scope to the North Atlantic — 21 of 131 ECMWF storms at 0 h — or make
  the extent data, which S4 already lists as open. **A hurricane track will
  leave the current box**, so this is not deferrable past the first map.
- **The tab is cheap and goes last.** The tab bar is a literal array in
  `src/App.js`; a fourth entry plus a component is the established pattern. One
  caution: `AnalysisTab.jsx` is 1,264 lines and on S4's deferred-refactor list.
  A cyclone tab should not become the fifth large component.

---

## 10. Open decisions, with owners

| # | decision | owner |
|---|---|---|
| ~~1~~ | ~~What feature 2 means~~ **DECIDED 2026-10-02: (c), the derived field. Specified in §6a.** | — |
| ~~2~~ | ~~Which IBTrACS vintage each product was scored against~~ **ANSWERED 2026-10-02 from the files.** | — |
| ~~3~~ | ~~What the June re-selection was selecting for~~ **ANSWERED 2026-10-02 from the files.** | — |
| 4 | What the `T` column is | open — **not blocking**, see below |
| ~~5~~ | ~~Which generation to load~~ **SETTLED by 2 and 3: `output/`, already loaded.** | — |
| 6 | North Atlantic only, or make the extent data | ours |

**2 and 3 were answered from the data rather than by email** (`TC_DATA_ACCESS.md`
§9), after the instruction to skip contacting `wang.shuoc` for now. Both were
provenance questions, and provenance turned out to be recoverable:

- **2.** `output/` was scored against the 2026-04-27 IBTrACS download, the April
  `storm_2016_2024_*` set against the 2025-09-17 one. The two vintages disagree
  for **24 of 138 storms**, so the two generations carry different truth and
  **must not be mixed**.
- **3.** A complete **+144 h** window. All **1,181** loaded runs reach exactly
  +144 h and none falls short, so the storms dropped between generations were
  excluded for not supplying a full six-day forecast — a selection on
  completeness, not on quality. Nothing was dropped for being wrong.
- **5** follows directly: `output/` has both the deeper lead and the newer best
  track, and mixing was never an option. It is what is loaded.

**4 stays open and is now explicitly not blocking.** The `T` column is not read
by the loader, is not stored, and is not used by any of the five views; every
number on screen derives from the forecast positions and the best track. If it
is ever wanted, it is one question — but nothing waits on it.

---

## 11. Sequence

1. ~~Settle decision 1.~~ **Done — §6a.**
2. Load `cyclone_track_member` + `cyclone_best_track` + `cyclone_run_registry`
   from `output/`, normalising per §8, recording `nominal_members` per §5.
3. Recompute the derived columns and report the difference (§7). **Do not
   proceed past a disagreement that has no explanation.**
4. Confirm track error grows with lead, per centre. That is the provenance gate.
5. ~~The spaghetti map and the denominator.~~ **BUILT 2026-10-02.**
   `/api/cyclones` and `/api/cyclone/tracks`, `src/components/CycloneTab.jsx`,
   a fourth tab, and 993,630 track rows over 1,181 runs loaded from `output/`
   (the loader reads 994,155; 525 are byte-identical repeats in one file,
   `kwbc_0h_MATTHEW.csv`, now counted and named at load time — `NEXT_STEPS.md`
   §37).

   **One track per member, chosen in one place.** `cyclone_track_member`'s key
   includes `cyclone_id`, so a member *may* carry two candidate cyclones. No run
   in this archive does — measured across all 1,181 source files, no member ever
   has more than one, at a lead or over its whole track. Every view here draws,
   scores and counts one track per member, so where that stops being true
   something must choose: longest candidate first, ties broken by earlier start
   then by id, applied in a single shared CTE rather than copied into three
   queries. `/api/cyclone/tracks` returns `variant_members` so a discarded
   candidate is stated rather than inferred. The fixture seeds one, because a
   selection rule nothing exercises is a rule nobody has tested.

   Two things the build found that no amount of design would have:

   **The antimeridian bites the renderer too, and differently.** Leaflet draws a
   polyline through increasing longitude, so a step from +179 to −179 is drawn
   as a 358° line back across the map. The first fix split the track into
   segments, which removed the streak and left two further problems — looking at
   GITA showed it as **two clusters on opposite edges of a world-zoomed map**,
   because `fitBounds` still received points at both −180 and +180. Unwrapping
   the longitudes past ±180 instead, every member against one shared reference,
   fixes all three at once. Independent of the `mean_lon` defect in the source
   data: same hazard, different layer, and neither fix helps the other.

   **One file of 1,181 carries two cyclone_id cycle stamps.**
   `egrr_72h_GITA.csv` holds 18 members stamped 06Z and 18 stamped 12Z —
   MOGREPS's time-lagged structure — while `valid_time - lead_time` reports a
   single init. The loader refused it rather than guess, and it was the only
   file of 1,181 it ever refused.

   **RESOLVED 2026-10-02, from the data, without the email.** All 36 members
   agree that `valid - lead` is 2018-02-12 12:00, and 431 of the 432 MOGREPS
   files carry exactly one stamp. So the file is internally coherent on a 12Z
   basis: the lagged members' leads *were* rebased, and the stamp records which
   cycle a member came from rather than asserting a second initialisation. 36
   members is also MOGREPS's full declared size, which only works if the two
   cycles are being combined.

   The old rule — "the stamp must be constant" — was the wrong *form* of a
   check that should exist. Two independent statements of the initialisation
   guard the §18/§20 defect, so the rule is now **causal**: a member may come
   from an earlier cycle, never a later one. A stamp after the init still
   refuses, because that is the two statements genuinely disagreeing.

   **The lag is recorded here and nowhere else, deliberately.** For this run
   it is **18 of 36** members carried forward from 06Z. A
   `lagged_members` column briefly existed and was removed on 2026-10-02, for
   a reason worth keeping:

   Only **1 of the 432** MOGREPS files discloses a lag at all. GITA's 12Z run
   stamps 18 members with the earlier cycle; **360** other 36-member files
   stamp every member with the nominal cycle. If MOGREPS always builds 36 from
   two cycles — which is how it is documented to work — those 360 are lagged in
   exactly the same way and simply do not say so.

   So the column read as a measurement while actually being a disclosure
   quirk: `0` meant *this file did not say*, not *not lagged*. Anything built
   on it, a caption most of all, would have fired on one run and implied the
   other 360 were same-cycle ensembles. A field that invites a false inference
   is worse than no field, so the loader no longer counts it and the API no
   longer returns it.

   What survives is the part that matters: the file **loads**, and a
   `cyclone_id` stamped *after* the init still refuses, because that is the
   two statements of the initialisation genuinely disagreeing (§18/§20).

   The honest version of this would be a statement about **MOGREPS** on all
   432 runs — *this ensemble is time-lagged; half its members are six hours
   older* — not a per-run number. It is not written because it has not been
   confirmed for those 360 files, only inferred from how MOGREPS is known to
   work, and inferring from how something is known to work is what produced
   the three longitude retractions in `TC_DATA_ACCESS.md`. One question to
   `wang.shuoc`, or one look at the tracker configuration, would settle it.

   Also: 6 rows of 994,161 carry only one coordinate, all in EMERAUDE. Dropped
   and counted, because a latitude with no longitude is not a position.
6. ~~Error-against-lead and spread-against-error.~~ **BUILT 2026-10-02** as one
   chart beside the map — `GET /api/cyclone/error-by-lead`,
   `cyclone_metrics.error_by_lead`, and the recharts idiom the comparison tab
   already uses.

   **Recomputed, not imported.** `compare_cyclone_derived.py` showed their
   `distance_km` is haversine at R = 6371.0 and reproduces to 2e-13 km, so the
   numbers are the same; the difference is that these have a derivation a reader
   can check — and the column beside it, `mean_lon`, was out by up to 213° with
   nothing to tell them apart. The ensemble mean here uses the **circular** mean.

   **A second denominator, which the build found and the design had not.**
   Members drop out at long leads as their forecast storm dissipates: Dorian's
   earliest ECMWF run falls from **28 members at +0 h to 4 at +144 h**. The line
   continues at full weight, so a reader would take the whole ensemble to be
   behind it. The count is now in the tooltip and the fall is stated in the
   caption. It is the same mistake as the headline denominator, one level down.

   ALCIDE reads as a calibrated ensemble — spread converging on error — which is
   the spread-skill question this application already asks, now in track space.
7. ~~Strike probability (§6a), with its invariant tests.~~ **BUILT 2026-10-02.**
   `Data/cyclone_metrics.py` (pure, no Flask and no database),
   `GET /api/cyclone/strike-probability`, and a toggle with an exposed radius on
   the cyclone tab.

   **The denominator is visible on screen, which was the point.** YASA from
   MOGREPS: *"23 of 36 members tracked this storm — the other 13 forecast no
   cyclone"*, and *"peak strike probability **64%** … of 36 members — not 23"*.
   64% is 23/36. Every tracked member passes through the peak cell, so the peak
   is bounded by the denominator; with the wrong one it would read **100%**,
   claiming certainty where a third of the ensemble forecast no storm at all.

   Two implementation notes worth keeping:

   **It marks cells near each track point rather than testing every cell.** The
   naive form is cells × points — about six million haversines for one storm,
   seconds per request in Python. A point only reaches cells within the radius,
   two or three in each direction at the default, so the work scales with track
   length rather than with the map.

   **Computed in unwrapped longitude and wrapped on the way out**, so a storm
   across ±180 is one field rather than two with a gap. That is the third
   independent fix for the same hazard — the source data's `mean_lon`, the
   renderer's polylines, and now the grid. None of the three helps the others.

Steps 2–4 are a loader and a comparison script, and are worth doing before any
frontend work: if step 3 or 4 fails, the visualisation would have been built on
numbers that do not mean what they say.
