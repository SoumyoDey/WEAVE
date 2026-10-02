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

## 2. The decision this document cannot make

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

**The recommendation is (c).** It is a genuine translucent layer, it answers
"do the scenarios cluster or diverge" more directly than fifty overplotted
polylines, it is the standard operational idiom, and it computes from 197 MB
already on disk. (a) and (c) look nearly identical in a mockup and differ
enormously in cost, which is exactly why the choice should be made deliberately
rather than discovered halfway through.

**Owner: whoever requested the feature.** Everything else in this document
holds under any of the three readings.

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

Four views, and only the first is new vocabulary:

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

Plus feature 2 as decided in §2; under reading (c) it is a fifth view and a
server-side derived field.

### Scale: there isn't a problem

51 members × 25 lead times = **1,275 points** for a storm-centre-offset, perhaps
50 KB of JSON. For comparison, one lead time of one gridded variable for 50
members is ~84,000 points, which is why `POINT_LIST_MAX_CELLS` exists.

**Feature 1 needs no cap, no tiling and no binary format.** Say so plainly, so
nobody imports the point-list machinery for a payload two orders of magnitude
smaller than the thing it was built for.

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

There is also a column `T` whose meaning nobody has established. **Do not load a
column nobody can name.**

**The provenance test**, the track analogue of §24's MAE-against-lead: track
error must grow monotonically with lead. A flat curve means the forecast is not
paired with its own valid times.

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
| 1 | **What feature 2 means** — (a), (b) or (c) in §2 | whoever requested it |
| 2 | Which IBTrACS vintage each product was scored against | `wang.shuoc` |
| 3 | What the June re-selection was selecting for | `wang.shuoc` |
| 4 | What the `T` column is | `wang.shuoc` |
| 5 | Which generation to load — `output/` (deeper lead) or the April set (more storms) | follows from 2 and 3 |
| 6 | North Atlantic only, or make the extent data | ours |

**1 and 5 block design; 2, 3 and 4 block trusting a number.** None of them block
loading the forecast positions themselves, which are unambiguous.

---

## 11. Sequence

1. Settle decision 1. Everything about feature 2 follows from it.
2. Load `cyclone_track_member` + `cyclone_best_track` + `cyclone_run_registry`
   from `output/`, normalising per §8, recording `nominal_members` per §5.
3. Recompute the derived columns and report the difference (§7). **Do not
   proceed past a disagreement that has no explanation.**
4. Confirm track error grows with lead, per centre. That is the provenance gate.
5. The spaghetti map and the denominator. This is the whole of feature 1.
6. Error-against-lead and spread-against-error, reusing the existing chart
   shapes.
7. Feature 2, as decided.

Steps 2–4 are a loader and a comparison script, and are worth doing before any
frontend work: if step 3 or 4 fails, the visualisation would have been built on
numbers that do not mean what they say.
