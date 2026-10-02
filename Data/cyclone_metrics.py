#!/usr/bin/env python
"""Fields derived from ensemble cyclone tracks.

`TC_TAB_DESIGN.md` §6a — §37's feature 2. The request was to "render all
individual model runs as semi-transparent layers at once, revealing whether
scenarios cluster tightly or diverge". Three readings were possible and the
chosen one is a field *derived* from the tracks, because the other two are
either feature 1 under another name or a fresh multi-gigabyte ingest of data
that is not on the cluster.

Strike probability, per cell: **the fraction of the ensemble whose track passes
within R km of that cell**, at any lead in the window.

Pure functions, no Flask and no database, so the arithmetic can be tested
against hand-built ensembles rather than against whatever happens to be loaded.

The denominator
---------------
**`nominal_members`, not the number of tracks supplied.** A member that forecast
no cyclone contributes a *no strike*, not an absence. Dividing by the members
that happened to produce a track would inflate every probability by up to
51/28 ≈ 1.8 — and it would do it worst on exactly the storms where the ensemble
disagreed about whether there would be a storm at all, which is where a reader
most needs the number to be honest.

That is the same shape as the export-divisor defect (`NEXT_STEPS.md` §13, §22):
a plausible number, silently wrong by a constant, with nothing downstream able
to tell. It is why `cyclone_run_registry` records `nominal_members` separately
from `tracked_members`.

Longitude
---------
Everything here works in **unwrapped** longitude — continuous past ±180 — and
the caller wraps the result back. A storm crossing the antimeridian is otherwise
split into two fields with a gap between them, which is the same hazard that
makes an arithmetic mean of longitudes wrong (`TC_DATA_ACCESS.md`) and that the
renderer has its own version of. Three layers, three fixes, none of which helps
the others.
"""
import math

EARTH_RADIUS_KM = 6371.0          # The radius `distance_km` was computed with,
                                  # verified against the source data, so our
                                  # distances and theirs mean the same thing.
DEFAULT_RADIUS_KM = 120.0         # The usual operational strike radius.
GRID_DEG = 0.5                    # The analysis lattice this app already uses.


def haversine_km(lat1, lon1, lat2, lon2):
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = p2 - p1
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * EARTH_RADIUS_KM * math.asin(min(1.0, math.sqrt(a)))


def unwrap(lons, reference=None):
    """Longitudes made continuous, so a track across ±180 is one line."""
    out, previous = [], reference
    for lon in lons:
        if previous is not None:
            while lon - previous > 180:
                lon -= 360
            while previous - lon > 180:
                lon += 360
        out.append(lon)
        previous = lon
    return out


def wrap(lon):
    """Back into [-180, 180) for the client."""
    return (lon + 180.0) % 360.0 - 180.0


def _snap(value, step):
    return math.floor(value / step) * step


def strike_probability(tracks, nominal_members, radius_km=DEFAULT_RADIUS_KM,
                       grid_deg=GRID_DEG):
    """[(lat, lon, probability)] over a lattice covering the ensemble.

    `tracks` is `{member_id: [(lat, lon), ...]}` with **unwrapped** longitudes.
    Only cells with a non-zero probability are returned: a strike field is
    mostly zero, and sending the zeros would be most of the payload.

    Computed by walking each track point and marking the cells near it, rather
    than by testing every cell against every point. The naive form is cells x
    points — about 6 million haversines for one storm, which is seconds per
    request in Python. A point only reaches cells within `radius_km`, which at
    the default is two or three cells in each direction, so the work is
    proportional to the track length instead of to the map.
    """
    if nominal_members <= 0:
        raise ValueError('nominal_members must be positive; it is the '
                         'denominator and a zero here would hide a loading bug')
    if radius_km <= 0:
        raise ValueError('radius_km must be positive')

    # member ids per cell, so a member passing a cell five times counts once.
    hit = {}
    # Latitude is uniform; longitude spacing shrinks with cos(lat), so the
    # longitude reach is computed per point rather than once.
    lat_reach = radius_km / 111.195

    for member, points in tracks.items():
        for lat, lon in points:
            if lat is None or lon is None:
                continue
            cos_lat = max(math.cos(math.radians(lat)), 1e-6)
            lon_reach = lat_reach / cos_lat
            lat0 = _snap(lat - lat_reach, grid_deg)
            lat1 = _snap(lat + lat_reach, grid_deg) + grid_deg
            lon0 = _snap(lon - lon_reach, grid_deg)
            lon1 = _snap(lon + lon_reach, grid_deg) + grid_deg

            cell_lat = lat0
            while cell_lat <= lat1 + 1e-9:
                cell_lon = lon0
                while cell_lon <= lon1 + 1e-9:
                    if haversine_km(lat, lon, cell_lat, cell_lon) <= radius_km:
                        hit.setdefault((round(cell_lat, 4), round(cell_lon, 4)),
                                       set()).add(member)
                    cell_lon += grid_deg
                cell_lat += grid_deg

    return [(lat, lon, len(members) / nominal_members)
            for (lat, lon), members in sorted(hit.items())]


def summarise(field):
    """(max, cells) — small, and enough for a test or a header to state."""
    if not field:
        return 0.0, 0
    return max(v for _, _, v in field), len(field)
