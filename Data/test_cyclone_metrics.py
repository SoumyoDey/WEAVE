"""Strike probability, against ensembles built by hand.

`TC_TAB_DESIGN.md` §6a. The invariants here are cheap and they catch the two
mistakes that matter: the wrong denominator, and a field that renders beautifully
while being unable to tell a tight ensemble from a scattered one.

The last of those is the §31 lesson — construct the case the metric is named for
and prove the metric detects it, rather than checking that it runs.
"""
import math

import pytest

import cyclone_metrics as cm


def line(lat, lon0, n=5, step=1.0, member_offset=0.0):
    """A straight west-going track, offset in latitude by member."""
    return [(lat + member_offset, lon0 - step * i) for i in range(n)]


class TestTheDenominator:
    def test_it_divides_by_the_members_that_RAN_not_the_tracks_supplied(self):
        """The whole argument for `nominal_members`.

        Four members tracked the storm out of fifty-one that ran. The other
        forty-seven forecast no cyclone, which is a *no strike*, so no cell can
        exceed 4/51. Dividing by the tracks supplied would put it at 1.0 and
        report certainty where the ensemble was mostly saying "no storm".
        """
        tracks = {m: line(20.0, -60.0) for m in range(4)}
        field = cm.strike_probability(tracks, nominal_members=51, radius_km=200)
        peak, _ = cm.summarise(field)
        assert peak == pytest.approx(4 / 51)
        assert peak < 0.1

    def test_a_full_ensemble_reaches_one(self):
        tracks = {m: line(20.0, -60.0) for m in range(10)}
        peak, _ = cm.summarise(
            cm.strike_probability(tracks, nominal_members=10, radius_km=200))
        assert peak == pytest.approx(1.0)

    def test_half_the_ensemble_reaches_one_half(self):
        tracks = {m: line(20.0, -60.0) for m in range(5)}
        peak, _ = cm.summarise(
            cm.strike_probability(tracks, nominal_members=10, radius_km=200))
        assert peak == pytest.approx(0.5)

    def test_a_zero_denominator_is_refused_rather_than_dividing(self):
        with pytest.raises(ValueError, match='denominator'):
            cm.strike_probability({0: line(20.0, -60.0)}, nominal_members=0)


class TestTheFieldIsAProbability:
    def test_every_value_is_in_range(self):
        tracks = {m: line(20.0, -60.0, member_offset=m * 0.3) for m in range(8)}
        field = cm.strike_probability(tracks, nominal_members=8, radius_km=150)
        assert field
        assert all(0.0 < v <= 1.0 for _, _, v in field)

    def test_a_member_counts_once_however_often_it_passes(self):
        """A track that loops through a cell five times is still one member
        striking it. Counting points rather than members would put the
        probability above 1."""
        looping = {0: [(20.0, -60.0)] * 5}
        field = cm.strike_probability(looping, nominal_members=1, radius_km=100)
        assert max(v for _, _, v in field) == pytest.approx(1.0)


class TestTheRadiusBehavesLikeARadius:
    def test_a_tiny_radius_marks_only_cells_a_track_passes_through(self):
        # 0.5 deg is ~55 km, so a 20 km radius can only reach a cell whose
        # centre is nearly under the track.
        tracks = {0: [(20.0, -60.0)]}
        field = cm.strike_probability(tracks, nominal_members=1, radius_km=20)
        assert len(field) <= 2
        for lat, lon, _ in field:
            assert cm.haversine_km(20.0, -60.0, lat, lon) <= 20

    def test_a_larger_radius_covers_more(self):
        tracks = {0: [(20.0, -60.0)]}
        small = cm.strike_probability(tracks, nominal_members=1, radius_km=60)
        large = cm.strike_probability(tracks, nominal_members=1, radius_km=300)
        assert len(large) > len(small)

    def test_no_cell_outside_the_radius_is_ever_marked(self):
        tracks = {0: line(20.0, -60.0)}
        field = cm.strike_probability(tracks, nominal_members=1, radius_km=120)
        for lat, lon, _ in field:
            assert min(cm.haversine_km(plat, plon, lat, lon)
                       for plat, plon in tracks[0]) <= 120 + 1e-6

    def test_a_nonpositive_radius_is_refused(self):
        with pytest.raises(ValueError, match='radius_km'):
            cm.strike_probability({0: line(20.0, -60.0)}, 1, radius_km=0)


class TestItCanTellClusteredFromDiverging:
    """The thing the feature exists to show, so the thing to assert.

    A field that could not separate these two would render beautifully and mean
    nothing — §31's lesson, where a binning scene was built specifically to
    prove the metric detected the artifact it was named for.
    """

    CLUSTERED = {m: line(20.0, -60.0, member_offset=m * 0.02) for m in range(20)}
    DIVERGING = {m: line(20.0, -60.0, member_offset=(m - 10) * 0.9) for m in range(20)}

    def test_a_tight_ensemble_gives_a_narrow_high_core(self):
        field = cm.strike_probability(self.CLUSTERED, 20, radius_km=120)
        peak, cells = cm.summarise(field)
        assert peak == pytest.approx(1.0)
        high = [c for c in field if c[2] >= 0.9]
        assert len(high) / cells > 0.5          # most of the field is the core

    def test_a_scattered_ensemble_gives_a_broad_low_field(self):
        field = cm.strike_probability(self.DIVERGING, 20, radius_km=120)
        peak, cells = cm.summarise(field)
        assert peak < 1.0
        high = [c for c in field if c[2] >= 0.9]
        assert len(high) / cells < 0.2

    def test_the_two_are_distinguishable_on_area_and_peak_together(self):
        tight = cm.strike_probability(self.CLUSTERED, 20, radius_km=120)
        broad = cm.strike_probability(self.DIVERGING, 20, radius_km=120)
        assert cm.summarise(broad)[1] > cm.summarise(tight)[1]   # wider
        assert cm.summarise(broad)[0] < cm.summarise(tight)[0]   # and less certain


class TestTheAntimeridian:
    def test_a_track_across_the_dateline_is_one_field_not_two(self):
        """Unwrapped input, so the storm does not split. The same hazard the
        source data's `mean_lon` fell into and the renderer has its own version
        of — three layers, three fixes."""
        crossing = {0: [(-20.0, 178.0), (-20.0, 179.0), (-20.0, 180.0),
                        (-20.0, 181.0), (-20.0, 182.0)]}
        field = cm.strike_probability(crossing, nominal_members=1, radius_km=120)
        lons = sorted({lon for _, lon, _ in field})
        # Contiguous in unwrapped space: no 360-degree hole in the middle.
        assert max(lons) - min(lons) < 20
        assert any(lon > 180 for lon in lons)

    def test_wrap_brings_it_back_for_the_client(self):
        assert cm.wrap(181.0) == pytest.approx(-179.0)
        assert cm.wrap(-181.0) == pytest.approx(179.0)
        assert cm.wrap(45.0) == pytest.approx(45.0)

    def test_unwrap_is_the_inverse_the_tracks_need(self):
        assert cm.unwrap([179.0, -179.0, -177.0]) == [179.0, 181.0, 183.0]


class TestItAgreesWithTheRestOfTheProject:
    def test_the_earth_radius_is_the_one_the_source_data_used(self):
        """`compare_cyclone_derived.py` established that the shipped
        `distance_km` is haversine at R=6371.0, reproduced to 2e-13 km. Using a
        different radius here would make our distances and theirs mean subtly
        different things."""
        assert cm.EARTH_RADIUS_KM == 6371.0

    def test_a_known_separation_comes_out_right(self):
        # One degree of latitude is 111.19 km on this sphere.
        assert cm.haversine_km(0.0, 0.0, 1.0, 0.0) == pytest.approx(111.19, abs=0.02)
