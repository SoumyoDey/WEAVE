# Finding and characterising the tropical-cyclone data on Explorer

**Status: not started. Written 2026-10-02.**

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
