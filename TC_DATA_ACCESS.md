# Finding and characterising the tropical-cyclone data on Explorer

**Status: stages A–C run 2026-10-02 — see §8, Findings. Stages D/E partly done.**

This is step 1 of `NEXT_STEPS.md` §37, and only step 1. It is about **locating
the data and writing down what is actually in it** — not about the track table,
the endpoints, or the tab. Those decisions depend on answers this document is
designed to produce, and making them first is how a schema gets built around a
file nobody opened.

**The path is `/projects/k.aggarwal/Shuochen`** (given 2026-10-02), and the
data is somewhere inside it. The directory is known; what is in it is not.

---

## 0. Why this has its own document

Because the last time this project went looking for data on Explorer, the search
itself produced two defects worth more than the data (§11):

**It looked in one directory and generalised to the filesystem.** The search
found `IMERG_6hourly/`, saw 6-hourly sampling, and concluded the cluster had no
half-hourly IMERG — so the project recorded a decision between "accept coarser
data" and "re-download from GES DISC with Earthdata credentials". Both halves
were wrong. `IMERG_complete/` held 4,416 half-hourly granules, 48 per day,
including every date needed. **There was never a decision to make.**

**And before that, "not on the development machine" was read as "does not
exist"** — for three weeks, while both sources sat on Explorer the whole time.

TC data multiplies the first risk. Different models, different dates and a
different structure means more directories that each *look* like the answer, and
"somewhere inside `Shuochen/`" is exactly the phrasing that invites stopping at
the first match. Knowing the root does not reduce this risk — it relocates it one
level down.

**So the rule for this survey: enumerate before concluding.** Do not report what
the TC data is until the whole tree has been listed and every candidate named,
including the ones being rejected and why.

---

## 1. Access

```
host   login.explorer.northeastern.edu      (Northeastern's Explorer cluster)
auth   key-based SSH — known to work (§11)
user   k.aggarwal  (assumed from /projects/k.aggarwal/WEAVE/; confirm at first login)
```

There is no `~/.ssh/config` entry for it on this machine, so connect explicitly:

```bash
ssh k.aggarwal@login.explorer.northeastern.edu
```

Three `explorer` entries already exist in `known_hosts`, so this machine has
connected before and the host key is established.

**Two cluster manners that are not optional.** Explorer runs Slurm, and a login
node is shared by everyone:

- Reading NetCDF/GRIB *headers* (`ncdump -h`, `h5ls`, `cdo sinfo`) is light and
  fine on a login node. So is a scoped `find`.
- A recursive `find /projects` unscoped, or anything that reads whole files, is
  not. Scope every search to a root, and take an interactive allocation
  (`srun --pty ...`) for real work.
- **Subset on the cluster, transfer the subset.** §11's precedent is exact: the
  global ERA5 file is 18.4 GB and the domain subset is 130 MB, cut by
  `era5_subset.py` on the cluster. Do not pull a TC ensemble across the wire to
  find out what is in it.

---

## 2. Whose directory is it?

**`/projects/k.aggarwal/Shuochen` is inside our own project allocation**, next
to `/projects/k.aggarwal/WEAVE/` — the directory §11 used for the ERA5 subsets.
So this is *not* the `/projects/s.dey/Puja/IMERG/` situation, where the standing
caution applies in full:

> It is group-readable, which is not the same as it being ours: **copy what you
> need rather than depending on it in place**, and ask before treating it as a
> project input. Its lifetime and permissions are not under our control.

That caution was written for someone else's project space and does not transfer
here. The lifetime and permissions of this path *are* under our control.

Two things still worth doing, for different reasons than permission:

1. **Record owner, group and mode anyway** (`ls -ld`, `stat`). A directory
   inside our allocation named after a person is most likely a collaborator's
   working area within it, and files written by another user can still be owned
   by them with a mode that does not let us read everything. Better to find that
   at stage A than halfway through a load.
2. **Ask Shuochen what it is — for the provenance, not the permission.** This is
   the trail §11 followed and got value from: `era5_subset.py` and
   `regions_config.json` sat beside the ERA5 data and explained how the subset
   was cut, which is how the bounds were confirmed to match
   `TARGET_LAT_RANGE`/`TARGET_LON_RANGE` rather than assumed to. Whoever
   produced the TC data knows which model, which tracker, and what was already
   applied to it. That is the fastest route to every answer in §3, and the
   cheapest. Nothing here is blocked on it.

## 3. The survey, in stages

Each stage ends with something written down. Nothing is concluded from a stage
that has not been completed.

### Stage A — confirm the root and its shape

The path is known, so this is verification rather than search:

```bash
ROOT=/projects/k.aggarwal/Shuochen
ls -ld "$ROOT"                       # owner, group, mode — see §2
du -sh  "$ROOT"                      # how much data is actually here
ls -l   "$ROOT"                      # the top level, in full
```

Record the full path, owner/group/mode, total size, and the top-level listing
**in full** — not the entries that look relevant. The entry that looks
irrelevant at stage A is the one §11 needed.

### Stage B — enumerate the whole tree before reading anything

```bash
ROOT=<the path from Stage A>
find "$ROOT" -maxdepth 4 -type d | sort                      # the shape
find "$ROOT" -type f -printf '%s\t%p\n' 2>/dev/null | sort -rn | head -50   # the big files
find "$ROOT" -type f -name '*.*' -printf '%f\n' | sed 's/.*\.//' | sort | uniq -c | sort -rn
```

That last one — a count by extension — is the cheapest answer to "what kind of
data is this": `.nc`, `.grb/.grib2`, `.dat`, `.txt`/`.atcf`, `.csv`, `.npy`.

**Write out every candidate directory**, with one line each saying what it
appears to hold and whether it is being taken forward. The directory that is
rejected needs its reason recorded; that is the step §11 skipped.

### Stage C — the question that sizes the whole project

**Is this tracker output, or raw fields?**

- **Tracker output** — cyclone centres already identified per member, typically
  ATCF (`a-deck`/`b-deck`), TC-vitals, or a CSV/text table with
  `(model, init, member, lead, lat, lon, mslp, vmax)`. This is a *loading job*.
- **Raw fields** — MSLP, vorticity or wind on a grid, from which centres must be
  derived per member per lead time. That is a **different project**: tracking
  algorithms, the splitting and merging of candidate centres, and a correctness
  standard nothing here currently has.

Nobody should estimate §37 before this is answered. Tell them apart by looking:

```bash
head -5 <a text file>                 # ATCF is comma-separated fixed fields
ncdump -h <a .nc file> | head -60     # dims and variables, no data read
```

### Stage D — characterise each candidate, to §11's standard

§11 is the bar, and it is a high one: *"Paths, contents and how each was
verified, so the next person can re-check rather than trust this."* For every
dataset taken forward, record:

| what | why it is on this list |
|---|---|
| Full path, size, file count | so it can be found again |
| Format and one sample's header | `ncdump -h`, or the first lines of text |
| **Models present**, and how named | §37's "different models" |
| **Initialisation times present** | §37's "different dates" — and see §4 below |
| **Member count per model** | ours are AIFS 50, GEFS 30, UKMO 18 |
| **Lead times and cadence** | tracks are usually 6-hourly; our fields are 3- and 6-hourly |
| **Units of every variable**, as stated *and* as checked | §13/§22 cost days to this |
| Geographic extent / basin | ours is ~24–46 N, −86 to −64 W; a track will leave it |
| Intensity fields available | min MSLP, max 10 m wind, RMW? |
| Owner, group, permissions | §2 above |

### Stage E — the units and conventions, checked rather than read

A stated unit is a claim, not a measurement. The three things that have actually
gone wrong here:

- **Accumulation windows.** The GEFS filenames say `3_Hour_Accumulation` on files
  holding 6-hour totals (Standing decisions). *Read the step from the file,
  never the name.*
- **Scaling.** `SCALED_EXPORT_DIVISOR_HOURS` exists because an export divided by
  a constant and nothing recorded it (§13, §22). Ask of any TC field: has
  anything already been divided out?
- **Longitude convention.** ERA5's subset is 275–295 °E, which is −85 to −65 W
  (§11). A track file in 0–360 and a map in ±180 will plot in the wrong ocean.

---

## 4. Dates — the part most likely to cost a week

§12 is the warning: a **4-hour UTC shift** in the precipitation truth but not the
wind truth moved every precipitation number in the app and **changed which model
looked better**. §20/§24: five of nine model/variable combinations held a
different run's data under the wrong label.

For TC data specifically:

- Record the **time zone and reference** of every time field verbatim
  (`units = "hours since ..."`), and whether lead time is stored or implied.
- Check the **file's own time variable against its filename**, for several
  files. All three converters now do this (`init_time_of`) and refuse a
  directory whose files disagree — a check added *after* §18/§20, because the
  AIFS wind stored at 2025-09-08 was the 2025-09-16 run and `time` said so in
  every one of those files. **Nothing read it.**
- Establish whether the TC dates overlap any loaded run (2025-09-08, 09-16).
  **Expect that they do not.** A storm is its own period, which means the
  scenario overlay (§37 feature 2) likely needs its own ingest rather than
  reading `regridded_forecast_member`.

---

## 5. Before any number is trusted

**MAE against lead time** (§24's method lesson 10). A forecast scored against its
own valid times loses skill monotonically with lead; the wrong week gives a flat
curve at a higher level. Row counts, grids, member counts and lead ranges were
identical between two different runs and told them apart not at all.

For tracks the equivalent is the same shape: **track error against lead time**,
against a best track. It should grow. A flat curve means the labels are wrong.

---

## 6. What the existing pipeline would require, if fields are reused

Only relevant if Stage C finds gridded fields and the intent is to run them
through the current converters. `convert_aifs.py` is strict, and deliberately:

- exactly **one** variable with dimensions `(number, latitude, longitude)` per
  file, else it refuses;
- lead time parsed from the **filename**;
- initialisation read from the file's own `time` scalar, and consistent across
  the directory.

A TC source will very likely not match this. That is fine and expected — the
point of recording it here is that "write a new converter" is the normal answer,
not a sign something is wrong. `convert_gefs.py` and `convert_ukmo.py` are the
precedent for a third.

---

## 7. The gate

This document is finished when someone can answer, in writing and from the
files:

1. Where the data is, who owns it, and whether we may use it.
2. Tracker output or raw fields.
3. Which models, which initialisations, how many members, what cadence.
4. The units and the time convention, checked rather than read.
5. The geographic extent, and how far outside our domain it goes.
6. Whether the dates overlap any loaded run.

**Then** §37's design note, and only then any code. The order is the point: this
project's two most expensive defects both came from building on a convention
nobody had verified.

---

---

## 8. Findings — stages A, B and C, run 2026-10-02

Read-only, from a login node. Every claim below was taken from a listing or a
file's own contents, and the ones that were *not* settled are named in §9.

### A — the root

```
/projects/k.aggarwal/Shuochen    drwxrws---+  wang.shuoc : k.aggarwal   140 GB
```

**Owned by `wang.shuoc`, group `k.aggarwal`.** §2 called this correctly: it is a
collaborator's working area inside our allocation. Readable — we are in the
group — and not ours to assume is stable.

**140 GB.** For scale, the entire current database is 123.52 GB and §27's
retention review sits at 250 GB. Copying this wholesale is not an option and is
not necessary; see `output/` below.

### B — the shape

```
Shuochen/
├── ecmf/   3,437 dirs   6,964 files     ECMWF
├── egrr/   4,324 dirs  17,997 files     UK Met Office
├── kwbc/   4,224 dirs  48,275 files     NCEP
│     └── <year>/<YYYYMMDD>/   2013 … 2024, plus storm_2016_2024_{0,12,24}h/
├── old/       11 dirs     690 files     earlier IBTrACS + MICHAEL test case
├── output/     1 dir    1,181 files     197 MB  ← the processed layer
├── ibtracs.ALL.list.v04r01.csv          330 MB  best track, all basins
└── storm.csv                             46 KB  IBTrACS extract, reaches 2025
```

75,109 files: **71,865 `.xml`**, 3,243 `.csv`, 1 `.nc`.

`ecmf` / `egrr` / `kwbc` are WMO centre codes, and they line up with the app's
three models — **with one trap.** The app's ECMWF model is **AIFS**, the AI
forecast system; `ecmf` here is the physics ensemble (`CENS`). Labelling this
data "AIFS" would be precisely the mislabel §20/§24 punished.

### C — tracker output, not raw fields

**This is the answer that sizes §37, and it is the cheap branch.**

Confirmed from the file, not the filename, as this project's rule requires:

```xml
<cxml ... cxml.1.1.xsd">
  <header><product>Cyclone Forecast</product>
    <generatingApplication><applicationType>Global ensemble prediction system</applicationType>
    <productionCenter>ECMWF</productionCenter>
    <baseTime>2024-12-31T00:00:00</baseTime>
  <data origin="ecmf" type="analysis">
    <disturbance ID="2024123100_175S_901E">
      <cycloneNumber>05S</cycloneNumber><basin>Southwest Pacific</basin>
      <fix source="synoptic"><validTime>2024-12-31T00:00:00Z</validTime>
        <latitude units="deg S" precision="0.1">-17.5</latitude>
        <longitude units="deg E" precision="0.1">90.1</longitude>
```

**CXML** (Cyclone XML, the BoM/THORPEX schema) from TIGGE — cyclone centres
already identified per member. No tracking algorithm is needed. The different
project §37 warned about is not this one.

### The `output/` directory is what to load

1,181 CSVs, **197 MB**, named `<centre>_<offset>h_<STORM>.csv`:

| centre | 0h | 24h | 48h | 72h |
|---|---|---|---|---|
| ecmf | 131 | 99 | 69 | 40 |
| egrr | 135 | 118 | 98 | 81 |
| kwbc | 134 | 111 | 92 | 73 |

**138 distinct storms.** The `0h/24h/48h/72h` in the name is an *initialisation
offset*, not forecast lead — `lead_time` is a column, and runs to 144 h.

The header is already most of feature 1:

```
member_id, cyclone_id, cycloneName, basin, time, lat, lon, pressure_hPa,
wind_mps, lead_time, NATURE, LAT, LON, DIST2LAND, LANDFALL, STORM_SPEED,
STORM_DIR, WMO_PRES, WMO_WIND, distance_km, T, mean_lat, mean_lon,
dist_to_ens_mean_km
```

Lower-case `lat`/`lon` are the **forecast** track; upper-case `LAT`/`LON` are the
**IBTrACS best track**, already matched in. `distance_km` is the track error,
`mean_lat`/`mean_lon`/`dist_to_ens_mean_km` the ensemble mean and the member's
distance from it. **Forecast, truth, and error are already joined** — which is
more than feature 1 needs, and supplies §5's provenance test for free.

`ecmf_0h_ALCIDE.csv`: 1,250 rows = **51 members (0–50) × 25 six-hourly steps to
+144 h**, exactly.

### Conventions, checked

- **Longitude in `output/` is signed ±180.** `ecmf_0h_BERYL.csv` runs −94.0 to
  −42.9 in the North Atlantic, and its first forecast point (9.2, −42.9) sits
  beside the best track (9.2, −43.1).
- ~~**The CXML files are 0–360 east.**~~ ~~**Retracted: the CXML is signed ±180
  as well.**~~ **Both statements were wrong, because both generalised from one
  centre.** The three centres encode longitude three different ways. See
  “`egrr/` and `kwbc/`” below — this is the single most important finding in
  this document.
- **Basin labels are not consistent between centres**: ECMWF writes
  `North Atlantic`, NCEP writes `AL`, for the same storm. Normalisation needed.
- Latitude carries `units="deg S"` with a *signed* value (−17.5), which the
  disturbance ID `..._175S_901E` cross-checks. The unit string is descriptive;
  the sign is the data. Do not apply both.

### Dates — the warning was right, by a decade

The archive is **2013–2024**. The loaded forecast runs are **2025-09-08** and
**2025-09-16**. They do not overlap at all, so §37 feature 2 (member fields)
cannot read `regridded_forecast_member` for these storms — there is no storm
period in the database. `storm.csv` reaches 2025-10 (MELISSA), so the best-track
side is more current than the forecast archive.

---

## 9. Still open after the survey

- ~~What `storm_2016_2024_{0,12,24}h/` holds.~~ **Answered below.**
- ~~Whether `output/` is complete or still generating.~~ **Answered below: it is
  complete.** The selection *criterion* is still open.
- ~~Whether `old/` is superseded.~~ **Answered below — it is, but one thing in
  it is not safely ignorable.**
- Member counts per centre, beyond ECMWF's 51. `kwbc_0h_BERYL.csv` has 767 rows
  against ecmf's 1,210, so they differ — by members, by track length, or both.
- Who produced `output/`, with what script, and whether it is reproducible.
  **This is the §2 question and still the cheapest next move:** ask
  `wang.shuoc`. It is the `era5_subset.py` trail that let §11 confirm bounds
  instead of assuming them.

---

---

## 10. What each remaining directory turned out to hold

### `storm_2016_2024_*h/` versus `output/` — two generations, not two stages

Checked 2026-10-02. `<centre>/storm_2016_2024_<offset>h/<STORM>.csv` holds the
same product as `output/`, per storm rather than per storm-and-centre, with two
extra pandas index columns (`Unnamed: 0`, `index`). It is **not** a pre-join
intermediate: every row already carries its best-track match, in both.

They are the same pipeline run twice, and they differ in three ways at once:

| | `storm_2016_2024_*h/` | `output/` |
|---|---|---|
| modified | 2026-04-06 | **2026-06-03** |
| initialisation offsets | 0, 12, 24 h | **0, 24, 48, 72 h** |
| forecast lead reaches | +72 h (13 steps) | **+144 h (25 steps)** |
| storms (ecmf) | **155** | 131 |
| size | 21 / 13 / 11 MB | 197 MB total |

`ecmf/storm_2016_2024_0h/ALCIDE.csv` is 51 members × 13 lead times = 663 rows;
`output/ecmf_0h_ALCIDE.csv` is 51 members × 25 lead times = 1,250 rows (not
1,275 — **one member's track is short**, so it is not a perfect rectangle and
nothing should assume it is).

**So `output/` is newer and goes twice as far in lead time, while the older set
covers ~20% more storms and a different offset grid.** Neither is a superset.
Twenty-nine storms in the older ecmf set — AMPHAN, HELENE, HILARY, KENNETH,
MOCHA, NORU and others — have no `output/` counterpart at 0 h.

**That is a decision, not a detail**, and it is the wrong kind to settle by
guessing: either `output/` is still being generated, or it was deliberately
narrowed and something disqualified those storms. Both readings fit the files.
Ask `wang.shuoc` — this is the same question as "who produced `output/`" below,
and now it has a concrete form.

### `old/` — a development history, and a truth-vintage problem

Checked 2026-10-02. 361 MB, and **superseded: nothing in it should be loaded.**
It is the work's own history, readable from the mtimes:

| when | what |
|---|---|
| 2025-09-17 | IBTrACS downloaded (CSV + NetCDF) |
| 2025-09-24 | `storm.csv`, `storm_gefs.csv` — early, per-centre storm lists |
| 2025-10-02 | `storm_2018_{0,24,48}h/` — first generation, one season |
| 2025-10-22 | `storm_[2018]_{0,24,48}h/` — **the same thing, renamed by a bug** |
| 2025-10-27/29 | `storm_[2013 … 2019]_{0,24,48}h/` — widened to seven seasons |
| 2026-01-09 | `MICHAEL_{ecmf,egrr,kwbc}_0h.csv` — single-storm test case |
| 2026-04-06 | *(current)* `<centre>/storm_2016_2024_{0,12,24}h/` |
| 2026-06-03 | *(current)* `output/` |

Three things in that are worth carrying forward.

**1. The best-track vintage is not constant, and that is a correctness problem.**
IBTrACS exists twice, and they are different downloads:

| | last record | downloaded |
|---|---|---|
| `old/ibtracs.ALL.list.v04r01.csv` | KAJIKI, 2025-08-24 | 2025-09-17 |
| `ibtracs.ALL.list.v04r01.csv` | SINLAKU, 2026-04-20 | **2026-04-27** |

IBTrACS is revised continuously, including **retrospectively** — a past storm's
best track changes between releases. The products carry `LAT`/`LON` and
`distance_km` computed against *a* best track, and which one follows from when
each was generated: `storm_2016_2024_*` predates the April download, `output/`
postdates it. **So the two current products may be scored against different
truth.** That is a hypothesis from mtimes, not a verified fact — but it is the
§12 shape exactly (two sources that look identical and are not), and it has to
be settled before any track error from these files is quoted.

**2. The offset grid is a parameter someone is still tuning**, not a property of
the data. It has been 0/24/48 (2025), then 0/12/24 (April), then 0/24/48/72
(June). Nothing should treat the current set as fixed.

**3. The tree contains failed runs.** `storm_[2013]_0h/` holds **zero files**.
And `storm_[2018]_0h/` sits beside `storm_2018_0h/` with identical counts three
weeks apart — the bracketed name is a stringified Python list reaching a path
(`f"storm_{years}_0h"` with `years=[2018]`). Neither is harmful here; both say
that in this tree **a directory existing does not mean it holds data**, which is
the §11 generalisation trap waiting to happen again.

**Also:** `storm.csv` is not a storm index. It is a scratch single-storm
best-track extract — `old/storm.csv` is MICHAEL (2018-10-06, Caribbean, 8
columns); the current one is **MELISSA only**, 2025-10-21 to 2025-11-01, in the
full IBTrACS column set. A loader that reads it as a catalogue of available
storms will be wrong about every one of them.

### `output/` is complete, not unfinished — checked 2026-10-02

The earlier note left two readings open: still being generated, or deliberately
narrowed. **It is narrowed.** Four independent checks, and the third is on its
own conclusive:

1. **One run, 59 minutes, four months ago.** Every one of the 1,181 files was
   written on 2026-06-03 between 13:23 and 14:22, in three clean per-centre
   batches — `kwbc` 13:23–13:25, `ecmf` 13:52–14:01, `egrr` 14:19–14:22. All
   three centres present, each ending cleanly. Nothing has touched the directory
   since. The last file written is `egrr_72h_YUTU.csv`: the alphabetically last
   storm at the deepest offset, which is where a *finished* loop ends and not
   where an interrupted one does.
2. **No in-progress markers** anywhere in the tree — no `.tmp`, `.part`,
   `.lock`, no editor swap files — and **no running jobs** for `wang.shuoc`.
3. **`output/` contains storms the April set does not**: ETA, IAN, IDA,
   KYAAR_KYARR, LAN. **A partial run cannot add storms.** This is the check that
   settles it, and it also means neither set is a subset of the other in either
   direction.
4. **The 29 ecmf storms absent at 0 h are absent at all four offsets** — 0 of 29
   appear at 24, 48 or 72 h. A storm-level exclusion, not a loop that stopped:
   an interrupted job drops whatever follows a point in its order, it does not
   drop the same 29 names consistently four times.

**So the question is no longer "is it finished" but "what was it selecting
for".** That is not visible from the basin mix, which rules out the obvious
guess — the loss is broad and roughly proportional, and the Atlantic actually
gains one:

| basin | Apr staged | `output/` |
|---|---|---|
| Northwest Pacific | 53 | 48 |
| Southwest Pacific | 43 | 32 |
| Northeast Pacific | 35 | 28 |
| North Atlantic | 20 | **21** |
| North Indian | 4 | 2 |

**A hypothesis that fits but is not verified:** the June run extends to +144 h
where April reached +72 h, so storms whose forecasts do not persist that far
would drop out — which would thin every basin rather than one, and is consistent
with the added storms (ETA, IAN, IDA) being long-lived major systems. Plausible,
unconfirmed, and cheap for `wang.shuoc` to confirm or deny.

One naming artifact for whoever writes the loader: `KYAAR_KYARR` carries an
underscore inside the storm name, so a filename parsed on `_` will split it
wrongly.

### `ecmf/` — the raw CXML archive, and a retraction

**First, the retraction, because it is a recorded fact that was wrong.**

§8 said *"the CXML files are 0–360 east, so the two layers disagree, and the
conversion already happened inside Shuochen's processing."* **That is false.**
Measured across a whole file: longitude runs **−180.0 to 179.9, with 9,943 of
29,293 values negative.** The CXML is signed ±180, exactly like `output/`. The
`units` attribute is descriptive and the sign is already in the value —
`units="deg E"` on `90.1`, `units="deg W"` on `−176.0`.

**How it happened is the part worth keeping.** The first sample I read was an
Indian Ocean disturbance at `90.1` with `units="deg E"`, and I concluded a
convention from one positive value in the eastern hemisphere, with no western
counter-example in front of me. That is the generalisation error §0 of this very
document quotes §11 for — *looked in one directory, generalised to the
filesystem* — committed inside the document that warns about it, two sections
later. **A convention needs a value that would falsify it, not a value
consistent with it.** There was no wrong-ocean trap; I invented one.

**The archive itself.** 41 GB, 2013–2024, 6,526 XML files in the year
directories:

```
ecmf/<year>/<YYYYMMDD>/z_tigge_c_ecmf_<YYYYMMDDHHMMSS>_ifs_glob_prod_all_glo.xml
```

Two files per date — **00Z and 12Z** — across 241–314 dates per year, so
coverage is most but not all of the calendar. Note the product string differs by
centre: ECMWF is `ifs … all`, NCEP is `CENS … esttr`. Not necessarily the same
TIGGE product, and worth confirming before the two are treated as equivalent.

**Each file is a complete ensemble**, which is what matters for feature 1:

```xml
<data origin="ecmf" type="analysis">
<data origin="ecmf" type="forecast">                                  <!-- deterministic -->
<data origin="ecmf" type="ensembleForecast" member="0"  perturb="control">
<data origin="ecmf" type="ensembleForecast" member="11" perturb="positive">
<data origin="ecmf" type="ensembleForecast" member="10" perturb="negative">
```

One `2024-09-01 00Z` file holds **1,215 `<disturbance>` elements, 14,671
`<fix>`es and 159 named cyclones**, globally, every basin. A fix carries its
lead as an attribute and its intensity alongside:

```xml
<fix hour="6" source="model">
  <validTime>2024-09-01T06:00:00Z</validTime>
  <latitude  units="deg N" precision="0.1">24.1</latitude>
  <longitude units="deg W" precision="0.1">-176.0</longitude>
  <cycloneData><minimumPressure source="model">
    <pressure units="hPa" precision="0.1">1009.0</pressure>
```

So **the raw archive carries everything feature 1 needs** — per-member tracks
with position, pressure, wind and speed — and `output/` is a 197 MB
pre-processed extract of the same thing, already joined to best track. The
archive is the fallback if the selection in `output/` turns out to be wrong for
our purposes; it is not a second source to reconcile.

### `egrr/` and `kwbc/` — three centres, three longitude encodings

**This is the finding that matters most here, and it took two wrong answers from
me to reach.**

| centre | encoding | the evidence that settles it |
|---|---|---|
| `ecmf` | **signed ±180**, `units` is decorative | `units="deg W"` carries `-100.1`; range −180.0 … 179.9, 9,943 negatives |
| `egrr` | **positive magnitude, `units` carries the sign** | `units="deg W"` carries `103.0` — *positive*; zero negatives, nothing above 180 |
| `kwbc` | **0–360 east**, only ever `units="deg E"` | max 188.2 (GEFS), **216.5** (CENS); no `deg W` element exists |

In one `egrr` file, `units="deg W">103.0<` and `units="deg E">100.2<` sit three
apart as numbers and **203 degrees apart on the Earth**. Read egrr's value
without its `units` attribute and the storm lands in the wrong hemisphere. The
wrong-ocean trap is real — it is just not where I first said it was, and not
where I said it was when I retracted that.

**My own error, twice, in opposite directions.** I first called the CXML 0–360
from one eastern `ecmf` value; measured `ecmf` properly, found signed ±180, and
retracted — generalising *again*, from the same single centre. Both statements
were over-generalisations with a sample of one. The rule §0 states, restated
because I broke it twice in one afternoon: **a convention is established by a
value that would falsify it.** For longitude that means a western-hemisphere
value, and for a multi-centre archive it means one *per centre*.

### What each directory actually holds

**`kwbc/` is a distribution node, not a model.** 66 GB, and it carries **two
production centres** — read from `<productionCenter>`, not inferred:

| product | `<productionCenter>` | kind | members |
|---|---|---|---|
| `GEFS … esttr` | NCEP | ensemble | **31** |
| `GFS … sttr` | NCEP | deterministic | — |
| `CENS … esttr` | **MSC** (Canada) | ensemble | **21** |
| `CMC … sttr` | **MSC** (Canada) | deterministic | — |

**Treating `kwbc/` as "GEFS" would silently blend American and Canadian
forecasts.** This is the §20/§24 mislabel with a new set of names, and the
directory layout actively invites it.

**`egrr/` is the Met Office**, 34 GB, two products: `mogreps … etctr`
(MOGREPS ensemble, **36 members**) and `mogm … tctr` (the deterministic global
model). Initialised **6-hourly** — 00/06/12/18Z — where `ecmf` is twice daily.

**Member counts differ by system and none match ours**: ECMWF 51, MOGREPS 36,
GEFS 31, CENS 21. Nothing should assume an ensemble size.

Sizes: `kwbc` 66 GB + `ecmf` 41 GB + `egrr` 34 GB = 141 GB, which is the tree.

## Open questions for whoever has context

- Which storm, or storms? One case to prove the feature, or a season?
- Can Shuochen say how the data was produced — which model, which tracker if
  any, and what was already applied to it? §2 argues this is the cheapest route
  to most of §3, and it is not blocking.
- Is `ROOT` a collaborator's working area inside our allocation, or a copy
  somebody staged there for this purpose? It changes whether it is safe to
  assume the contents are stable.
- Is the intent a historical case study, or something that would eventually run
  on new storms? That changes whether the ingest needs to be scripted to the
  standard `DATA_EXPANSION_DESIGN.md` phase 4 set for forecasts.
