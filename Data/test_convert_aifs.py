"""Tests for `convert_aifs.py`.

What is pinned here is the set of conventions that were *not* guessable from
either neighbouring script and that produce a table which loads cleanly and is
wrong. Each was established by measurement against the loaded AIFS run (see the
module docstring), so each is a regression guard rather than a restatement of
the implementation.

Two tiers, deliberately:

* The numeric conventions -- threshold, rounding, the mean/std coupling -- are
  tested against plain arrays and run everywhere, including CI.
* The file-reading conventions need netCDF4, which is not in
  `Data/requirements.txt`, so they build tiny NetCDF files in a tmpdir and skip
  themselves where it is absent. Same bargain as the PostgreSQL tests.

**The synthetic grids here are deliberately non-square.** The real domain is
81x81, which makes a transposed read completely silent; a 5x7 grid turns the
same mistake into an error. That is the one lesson `load_observations.py` paid
for twice.
"""
import json

import numpy as np
import pytest

import convert_aifs as ca


LATS = np.array([25.0, 25.25, 25.5, 25.75, 26.0])           # 5
LONS = np.array([-85.0, -84.75, -84.5, -84.25, -84.0, -83.75, -83.5])   # 7


def field(values):
    """A (member, lat, lon) float32 block from a list of 2-D layers."""
    return np.asarray(values, dtype=np.float32)


class TestTheLeadTimeComesFromTheFilename:
    """The loader defaults a missing hour to 0, so a name it cannot parse would
    pile a whole forecast onto the analysis time rather than fail."""

    @pytest.mark.parametrize('name,expected', [
        ('conus_east_20250908000000-6h-enfo-pf_tp.nc', 6),
        ('conus_east_20250908000000-0h-enfo-pf_tp.nc', 0),
        ('conus_east_20250908000000-360h-enfo-pf_tp.nc', 360),
        ('conus_east_20250908000000-120h-enfo-pf_u10.nc', 120),
    ])
    def test_it_reads_the_hour(self, name, expected):
        assert ca.forecast_hour(name) == expected

    def test_it_returns_none_rather_than_zero_when_absent(self):
        assert ca.forecast_hour('conus_east_20250908000000-enfo-pf_tp.nc') is None

    def test_it_agrees_with_the_loader(self):
        """`load_to_postgres.py` parses the hour with its own regex. If the two
        ever disagree the data lands under the wrong lead time, which no
        aggregate would reveal."""
        loader = pytest.importorskip('load_to_postgres')
        name = 'conus_east_20250908000000-42h-enfo-pf_tp_member_07.json'
        got_hour, got_member, got_type = (
            loader.WeatherDataLoader.extract_metadata_from_filename(
                loader.WeatherDataLoader.__new__(loader.WeatherDataLoader), name))
        assert got_hour == ca.forecast_hour(name) == 42
        assert got_member == 7 and got_type == 'member'


class TestThePrecipitationThreshold:
    """0.01 mm is the loaded run's boundary, measured: everything dropped is
    <= 0.00977 mm and everything kept >= 0.01074 mm, with no overlap."""

    def test_values_below_the_threshold_are_dropped(self):
        grid = np.full((5, 7), 0.009, dtype=np.float32)
        assert ca._points(grid, LATS, LONS, ca.MIN_PRECIP_MM, 3) == []

    def test_values_at_or_above_it_are_kept(self):
        grid = np.full((5, 7), 0.011, dtype=np.float32)
        assert len(ca._points(grid, LATS, LONS, ca.MIN_PRECIP_MM, 3)) == 35

    def test_exact_zero_is_dropped(self):
        """Hour 0 of a cumulative field is all zeros, which is why the database
        has no hour 0 for AIFS precipitation -- 0 of 6,561 cells qualify."""
        grid = np.zeros((5, 7), dtype=np.float32)
        assert ca._points(grid, LATS, LONS, ca.MIN_PRECIP_MM, 3) == []

    def test_no_threshold_keeps_zeros_and_negatives(self):
        """Wind is instantaneous: 0 m/s is a reading and negative is half the
        domain, so applying the precipitation threshold would delete data."""
        grid = np.array([[0.0, -3.5, 2.25, 0.0, -0.001, 9.0, -12.5]] * 5,
                        dtype=np.float32)
        records = ca._points(grid, LATS, LONS, None, 3)
        assert len(records) == 35
        assert min(r['value'] for r in records) == -12.5

    def test_nan_is_dropped_whatever_the_threshold(self):
        grid = np.full((5, 7), np.nan, dtype=np.float32)
        assert ca._points(grid, LATS, LONS, None, 3) == []
        assert ca._points(grid, LATS, LONS, ca.MIN_PRECIP_MM, 3) == []


class TestRounding:
    def test_values_round_to_three_decimals_in_source_units(self):
        grid = np.array([[1.23456] * 7] * 5, dtype=np.float32)
        assert ca._points(grid, LATS, LONS, None, 3)[0]['value'] == 1.235

    def test_it_does_not_divide_by_the_emit_interval(self):
        """The /6 belongs to `aifs react.py`. Doing it here as well would make
        every precipitation score a sixth of what it should be, with no error."""
        grid = np.full((5, 7), 6.0, dtype=np.float32)
        assert ca._points(grid, LATS, LONS, None, 3)[0]['value'] == 6.0

    def test_it_does_not_apply_the_ukmo_unit_conversion(self):
        """`tp` is kg m**-2, already millimetres. UKMO's `total_rainfall_rate`
        is m/s and needs x3.6e6; applying that here would inflate rainfall by
        six orders of magnitude."""
        grid = np.full((5, 7), 2.0, dtype=np.float32)
        assert ca._points(grid, LATS, LONS, None, 3)[0]['value'] == 2.0

    def test_coordinates_are_rounded_to_the_stored_precision(self):
        grid = np.full((5, 7), 1.0, dtype=np.float32)
        record = ca._points(grid, LATS, LONS, None, 3)[0]
        assert record['lat'] == 25.0 and record['lon'] == -85.0


class TestEnsembleStatistics:
    def test_std_is_the_population_deviation(self):
        """ddof=1 mismatches 362,979 of 378,737 stored rows, so the two are
        easy to separate once compared and impossible to tell apart by reading
        either script."""
        values = field([np.full((5, 7), 1.0), np.full((5, 7), 3.0)])
        _, std = ca.ensemble_stats(values, LATS, LONS, None, 6)
        assert std[0]['value'] == 1.0          # ddof=0 -> 1.0; ddof=1 -> 1.414214

    def test_mean_is_over_members(self):
        values = field([np.full((5, 7), 1.0), np.full((5, 7), 4.0)])
        mean, _ = ca.ensemble_stats(values, LATS, LONS, None, 3)
        assert mean[0]['value'] == 2.5

    def test_std_is_written_only_where_mean_survives_the_threshold(self):
        """The loader applies std with an UPDATE keyed on the statistics row, so
        a std at a cell with no mean is discarded in silence."""
        layer = np.full((5, 7), 0.002, dtype=np.float32)
        layer[0, 0] = 5.0                       # one cell clears the threshold
        values = field([layer, layer * 2])
        mean, std = ca.ensemble_stats(values, LATS, LONS, ca.MIN_PRECIP_MM, 3)
        assert {(r['lat'], r['lon']) for r in std} == {(r['lat'], r['lon']) for r in mean}
        assert len(mean) == 1

    def test_a_mean_exactly_at_the_threshold_is_dropped(self):
        """The cell that caught this. float32's 0.01 is 0.00999999977 in
        float64, so it is *below* the threshold -- but `mean_array < 0.01` in
        numpy casts the Python float down to float32, where it compares equal
        and the cell is kept. One cell of the loaded run, (44.75, -83.0) at
        +6h, sits exactly there.

        Still true under numpy 2.4's NEP 50 promotion, which is why this is
        pinned rather than trusted.
        """
        values = field([np.full((5, 7), 0.01)])
        assert float(np.nanmean(values, axis=0)[0, 0]) < ca.MIN_PRECIP_MM
        assert not bool((np.nanmean(values, axis=0) < ca.MIN_PRECIP_MM)[0, 0])
        mean, std = ca.ensemble_stats(values, LATS, LONS, ca.MIN_PRECIP_MM, 3)
        assert mean == [] and std == []


# --------------------------------------------------------------------------
# Everything below reads real NetCDF, and skips where netCDF4 is absent.
# --------------------------------------------------------------------------

def write_nc(path, values, lats=LATS, lons=LONS, name='tp',
             dim_order=('number', 'latitude', 'longitude')):
    """A minimal AIFS-shaped file. `dim_order` lets a test permute the axes."""
    nc = pytest.importorskip('netCDF4')
    values = np.asarray(values, dtype=np.float32)
    sizes = {'number': values.shape[0], 'latitude': lats.size, 'longitude': lons.size}
    with nc.Dataset(path, 'w') as ds:
        for dim, size in sizes.items():
            ds.createDimension(dim, size)
        ds.createVariable('number', 'i8', ('number',))[:] = np.arange(1, sizes['number'] + 1)
        ds.createVariable('latitude', 'f8', ('latitude',))[:] = lats
        ds.createVariable('longitude', 'f8', ('longitude',))[:] = lons
        var = ds.createVariable(name, 'f4', dim_order)
        source = {'number': 0, 'latitude': 1, 'longitude': 2}
        var[:] = np.transpose(values, [source[d] for d in dim_order])
    return path


class TestReadingTheField:
    def test_axes_come_back_as_member_lat_lon(self, tmp_path):
        values = np.arange(2 * 5 * 7, dtype=np.float32).reshape(2, 5, 7)
        path = write_nc(tmp_path / 'conus_east_x-6h-enfo-pf_tp.nc', values)
        got, lats, lons, name = ca.read_field(path)
        assert got.shape == (2, 5, 7) and name == 'tp'
        np.testing.assert_array_equal(got, values)
        np.testing.assert_array_equal(lats, LATS)
        np.testing.assert_array_equal(lons, LONS)

    def test_a_permuted_file_is_still_read_correctly(self, tmp_path):
        """Axes are resolved by dimension name. On the real 81x81 domain a
        positional read of a permuted file would be silently transposed."""
        values = np.arange(2 * 5 * 7, dtype=np.float32).reshape(2, 5, 7)
        path = write_nc(tmp_path / 'conus_east_x-6h-enfo-pf_tp.nc', values,
                        dim_order=('latitude', 'longitude', 'number'))
        got, _, _, _ = ca.read_field(path)
        assert got.shape == (2, 5, 7)
        np.testing.assert_array_equal(got, values)

    def test_the_latitude_order_in_the_file_is_preserved(self, tmp_path):
        """The real files carry `stored_direction = "decreasing"` while the
        array ascends. Reordering on the strength of that attribute would flip
        the domain."""
        descending = LATS[::-1].copy()
        values = np.arange(1 * 5 * 7, dtype=np.float32).reshape(1, 5, 7)
        path = write_nc(tmp_path / 'conus_east_x-6h-enfo-pf_tp.nc', values,
                        lats=descending)
        _, lats, _, _ = ca.read_field(path)
        np.testing.assert_array_equal(lats, descending)

    def test_a_grid_mismatch_is_refused(self, tmp_path):
        """A coordinate vector shorter than the axis it labels would otherwise
        silently truncate the domain, since `_points` iterates the coordinates.

        Built by giving `latitude` a *different* dimension from the one `tp`
        uses, which is the only way to get the two out of step in a file
        netCDF4 will write.
        """
        nc = pytest.importorskip('netCDF4')
        path = tmp_path / 'conus_east_x-6h-enfo-pf_tp.nc'
        with nc.Dataset(path, 'w') as ds:
            ds.createDimension('number', 1)
            ds.createDimension('latitude', 5)
            ds.createDimension('longitude', 7)
            ds.createDimension('lat_short', 3)
            ds.createVariable('latitude', 'f8', ('lat_short',))[:] = LATS[:3]
            ds.createVariable('longitude', 'f8', ('longitude',))[:] = LONS
            ds.createVariable('tp', 'f4', ('number', 'latitude', 'longitude'))[:] = 0
        with pytest.raises(ca.ConversionError, match='but the grid is'):
            ca.read_field(path)

    def test_a_sentinel_value_is_treated_as_missing(self, tmp_path):
        """`tp` carries GRIB_missingValue 3.4e38. Left in place it would be
        written out as rainfall of 3.4e38."""
        values = np.full((1, 5, 7), 3.40282346638529e+38, dtype=np.float32)
        path = write_nc(tmp_path / 'conus_east_x-6h-enfo-pf_tp.nc', values)
        got, _, _, _ = ca.read_field(path)
        assert np.isnan(got).all()

    def test_a_file_with_no_matching_variable_is_refused(self, tmp_path):
        nc = pytest.importorskip('netCDF4')
        path = tmp_path / 'conus_east_x-6h-enfo-pf_tp.nc'
        with nc.Dataset(path, 'w') as ds:
            ds.createDimension('latitude', 5)
            ds.createVariable('latitude', 'f8', ('latitude',))[:] = LATS
        with pytest.raises(ca.ConversionError, match='exactly one'):
            ca.read_field(path)


class TestConvertingAFile:
    def test_the_member_index_is_the_array_position_not_the_number_variable(self, tmp_path):
        """`number` runs 1..50 and the database holds 0..49. Writing the
        `number` value would shift every member by one, invisibly."""
        values = field([np.full((5, 7), 1.0), np.full((5, 7), 2.0)])
        path = write_nc(tmp_path / 'conus_east_x-6h-enfo-pf_tp.nc', values)
        out = tmp_path / 'json'
        written = ca.convert_file(path, out, write_stats=False)
        assert set(written) == {'conus_east_x-6h-enfo-pf_tp_member_00.json',
                                'conus_east_x-6h-enfo-pf_tp_member_01.json'}
        first = json.loads((out / 'conus_east_x-6h-enfo-pf_tp_member_00.json').read_text())
        assert first[0]['value'] == 1.0          # number 1 -> member_00

    def test_output_names_are_the_source_stem_plus_a_suffix(self, tmp_path):
        values = field([np.full((5, 7), 1.0)])
        path = write_nc(tmp_path / 'conus_east_20250908000000-42h-enfo-pf_tp.nc', values)
        written = ca.convert_file(path, tmp_path / 'json')
        assert sorted(written) == [
            'conus_east_20250908000000-42h-enfo-pf_tp_mean.json',
            'conus_east_20250908000000-42h-enfo-pf_tp_member_00.json',
            'conus_east_20250908000000-42h-enfo-pf_tp_std.json',
        ]

    def test_an_all_zero_hour_writes_an_empty_member_file(self, tmp_path):
        """Hour 0 of a cumulative field. An empty file is the correct output and
        the loader treats it as zero rows, which is why the database has no
        hour 0."""
        path = write_nc(tmp_path / 'conus_east_x-0h-enfo-pf_tp.nc',
                        np.zeros((1, 5, 7), dtype=np.float32))
        out = tmp_path / 'json'
        written = ca.convert_file(path, out, write_stats=False)
        assert written == {'conus_east_x-0h-enfo-pf_tp_member_00.json': 0}
        assert json.loads((out / 'conus_east_x-0h-enfo-pf_tp_member_00.json').read_text()) == []

    def test_wind_gets_no_threshold_without_being_asked(self, tmp_path):
        """The threshold is chosen from the variable, so converting wind cannot
        quietly inherit the precipitation rule."""
        values = np.zeros((1, 5, 7), dtype=np.float32)
        path = write_nc(tmp_path / 'conus_east_x-6h-enfo-pf_u10.nc', values, name='u10')
        written = ca.convert_file(path, tmp_path / 'json', write_stats=False)
        assert written['conus_east_x-6h-enfo-pf_u10_member_00.json'] == 35


class TestConvertingAFolder:
    def test_a_file_without_a_lead_time_stops_the_run(self, tmp_path):
        """Rather than being loaded as hour 0."""
        src = tmp_path / 'src'
        src.mkdir()
        write_nc(src / 'conus_east_x-6h-enfo-pf_tp.nc', np.ones((1, 5, 7), dtype=np.float32))
        write_nc(src / 'conus_east_x-enfo-pf_tp.nc', np.ones((1, 5, 7), dtype=np.float32))
        with pytest.raises(ca.ConversionError, match='no `-<N>h-` lead time'):
            ca.convert_folder(src, tmp_path / 'json')

    def test_an_empty_source_is_refused(self, tmp_path):
        pytest.importorskip('netCDF4')
        src = tmp_path / 'empty'
        src.mkdir()
        with pytest.raises(ca.ConversionError, match='no .nc files'):
            ca.convert_folder(src, tmp_path / 'json')

    def test_it_converts_every_file_in_lead_time_order(self, tmp_path):
        src = tmp_path / 'src'
        src.mkdir()
        for hour in (0, 6, 120):
            write_nc(src / f'conus_east_x-{hour}h-enfo-pf_tp.nc',
                     np.full((2, 5, 7), 1.0, dtype=np.float32))
        totals = ca.convert_folder(src, tmp_path / 'json')
        assert totals['files'] == 3
        # 3 hours x (2 members + mean + std) x 35 cells
        assert totals['records'] == 3 * 4 * 35
