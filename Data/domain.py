"""The analysis domain: one definition, overridable, checked against the data.

The 0.5-degree box every scored endpoint reads was written out twice — as
`TARGET_LAT_RANGE`/`TARGET_LON_RANGE` in `regrid_members.py`, which decides
what gets *loaded*, and as `DEFAULT_REGION` in `flask_api.py`, which decides
what gets *served* when a request names no box. Two copies of one fact, on
opposite sides of the ingest boundary (`NEXT_STEPS.md` §76).

**Why this module has no imports worth mentioning.** `regrid_members` is a
loader CLI that pulls in scipy and opens a database connection at import;
`flask_api` is the web app. Neither can import the other for four numbers —
`test_default_region.py` had to parse the loader's *source text* to compare
them, which worked and should not have been necessary. A module that imports
nothing but `os` can be imported by both.

## Changing it is an ingest-time decision, not a runtime one

The environment variables below are read once, at import. That is deliberate
and the limitation is the point: **the domain describes data that is already on
disk.** Re-pointing a running API at a different box does not move the 42
million rows that were regridded onto the old one; it just makes the API's
idea of "the domain" disagree with the database, which is §24's defect — a
confident statement about something no longer true.

So the order is: change the variable, re-run the regrid, reload. And because
nobody will remember that, `_check_domain` in `flask_api.py` compares these
numbers against the extent actually stored and says so on `/api/health` when
they have drifted apart. **Configurable without a check is worse than
hard-coded**: a constant can only be wrong if someone edits the file, while a
variable can be wrong because of a shell.

## Format

    WEAVE_DOMAIN_LAT=25,45
    WEAVE_DOMAIN_LON=-85,-65
    WEAVE_DOMAIN_RESOLUTION=0.5

A malformed value raises at import rather than falling back to the default.
Starting with a *different* domain than the operator asked for is the one
outcome worse than refusing to start, because every number served afterwards
would be quietly scoped to the wrong box.
"""
import os


DEFAULT_LAT_RANGE  = (25.0, 45.0)
DEFAULT_LON_RANGE  = (-85.0, -65.0)
DEFAULT_RESOLUTION = 0.5


def _pair(name, default):
    """`"lo,hi"` from the environment, or `default`.

    Validated here rather than at the call sites: a reversed or non-numeric
    range is a configuration error, and the moment to say so is startup.
    """
    raw = os.environ.get(name)
    if raw is None or raw.strip() == '':
        return default
    parts = raw.split(',')
    if len(parts) != 2:
        raise ValueError(f'{name} must be "lo,hi" (got {raw!r})')
    try:
        lo, hi = (float(p) for p in parts)
    except ValueError:
        raise ValueError(f'{name} must be two numbers (got {raw!r})') from None
    if lo >= hi:
        raise ValueError(f'{name} must have lo < hi (got {raw!r})')
    return (lo, hi)


def _resolution(name, default):
    raw = os.environ.get(name)
    if raw is None or raw.strip() == '':
        return default
    try:
        value = float(raw)
    except ValueError:
        raise ValueError(f'{name} must be a number (got {raw!r})') from None
    if value <= 0:
        raise ValueError(f'{name} must be positive (got {raw!r})')
    return value


LAT_RANGE  = _pair('WEAVE_DOMAIN_LAT', DEFAULT_LAT_RANGE)
LON_RANGE  = _pair('WEAVE_DOMAIN_LON', DEFAULT_LON_RANGE)
RESOLUTION = _resolution('WEAVE_DOMAIN_RESOLUTION', DEFAULT_RESOLUTION)


def as_bbox():
    """The domain in the `min_lat/max_lat/min_lon/max_lon` shape the API uses."""
    return {
        'min_lat': LAT_RANGE[0], 'max_lat': LAT_RANGE[1],
        'min_lon': LON_RANGE[0], 'max_lon': LON_RANGE[1],
    }


def is_default():
    """Whether the domain is the compiled-in one.

    Reported on `/api/health` so a reader can tell "the usual box" from "the
    box someone set in a shell", which is the first question when a number
    looks wrong.
    """
    return (LAT_RANGE == DEFAULT_LAT_RANGE
            and LON_RANGE == DEFAULT_LON_RANGE
            and RESOLUTION == DEFAULT_RESOLUTION)
