"""The SQL member-moment path against the Python reference it replaced.

`_member_moments_sql` restates `_precip_member_rate_series`,
`_increment_divisor` and `_rebin_member_to_common_window` in SQL so that the
full domain ships ~47k rows of pooled moments instead of 2.35M member rows
(`NEXT_STEPS.md` §52). A restatement in another language is only safe while
something checks it against the original, and that is what this file is:
`_member_moments_python` is kept in `flask_api.py` for no other purpose.

**If one of these fails, the two implementations have drifted — do not "fix"
the test.** Find which side changed. The arithmetic belongs to `metrics.py`
and both sides are supposed to be reading it.

The fixture is built for this comparison without trying: the three models hold
the same true field in three different storage conventions, so a single
reference run exercises the cumulative path (AIFS), the mixed 3 h/6 h bucket
path (GEFS) and the hourly re-binning path (UKMO) at once.
"""
import math

import pytest

import fixture_db as fx

BOX = {'min_lat': 35.0, 'max_lat': 37.0, 'min_lon': -76.0, 'max_lon': -74.0}
# Both halves of the fixture's record: inside the observed window and past it.
HOURS = set(range(0, fx.PRECIP_HOUR_MAX + 1))

CASES = [(m, v) for m in fx.MODELS for v in ('precipitation', 'wind')]

# **Why this is 2e-7 and not 1e-12.** Both sides read the same stored `real`,
# and they widen it differently: psycopg2 parses the shortest decimal the
# server prints (`2.4` -> 2.4), while SQL arithmetic widens the exact binary
# float4 (`2.4` -> 2.4000000953674316). Same stored value, two legitimate
# readings, differing by about float32 epsilon. That is below the 4 decimal
# places every endpoint rounds to, and §52 checks the rendered payloads are
# identical rather than taking this on trust. A real arithmetic divergence —
# the wrong divisor, a missed difference, a re-bin that drops a record — is
# orders of magnitude bigger than this and still fails.
FLOAT4 = dict(rel=2e-7, abs=1e-12)


def _both(cursor, model, variable, hours=None, **box):
    import flask_api as api
    kwargs = dict(source_hours=None, targets=None)
    if hours is not None:
        kwargs = dict(source_hours=api._window_source_hours(
            model, sorted(hours), variable == 'wind'), targets=sorted(hours))
    args = (cursor, model, variable, fx.INIT_TIME,
            box.get('min_lat', BOX['min_lat']), box.get('max_lat', BOX['max_lat']),
            box.get('min_lon', BOX['min_lon']), box.get('max_lon', BOX['max_lon']))
    return (api._member_moments_sql(*args, **kwargs),
            api._member_moments_python(*args, **kwargs))


class TestTheTwoImplementationsAgree:

    @pytest.mark.parametrize('model,variable', CASES)
    def test_the_same_cells_and_lead_times_are_scored(self, db_cursor, model, variable):
        """Coverage first: a faster path that quietly drops records would pass
        every value comparison below on the ones it kept."""
        sql, ref = _both(db_cursor, model, variable, HOURS)
        assert set(sql) == set(ref), (
            f'cells differ: only SQL {set(sql) - set(ref)}, '
            f'only reference {set(ref) - set(sql)}')
        assert sql, 'both empty — the comparison would be vacuous'
        for cell in ref:
            assert set(sql[cell]) == set(ref[cell]), f'lead times differ at {cell}'

    @pytest.mark.parametrize('model,variable', CASES)
    def test_every_moment_matches(self, db_cursor, model, variable):
        sql, ref = _both(db_cursor, model, variable, HOURS)
        for cell, by_hour in ref.items():
            for hour, (mean, spread_sq, n) in by_hour.items():
                s_mean, s_spread_sq, s_n = sql[cell][hour]
                where = f'{model}/{variable} {cell} +{hour}h'
                assert s_n == n, f'member count at {where}'
                assert s_mean == pytest.approx(mean, **FLOAT4), where
                assert s_spread_sq == pytest.approx(spread_sq, **FLOAT4), where

    @pytest.mark.parametrize('model,variable', CASES)
    def test_they_agree_with_no_hour_restriction(self, db_cursor, model, variable):
        """`hours=None` is a different query — no hour predicate and no target
        filter — and it is the shape /api/spread-skill uses."""
        sql, ref = _both(db_cursor, model, variable)
        assert set(sql) == set(ref)
        for cell in ref:
            assert set(sql[cell]) == set(ref[cell]), f'lead times differ at {cell}'
            for hour in ref[cell]:
                assert sql[cell][hour][0] == pytest.approx(ref[cell][hour][0], **FLOAT4)

    def test_a_box_with_no_data_is_empty_both_ways(self, db_cursor):
        sql, ref = _both(db_cursor, 'AIFS', 'precipitation', HOURS,
                         min_lat=10.0, max_lat=11.0, min_lon=10.0, max_lon=11.0)
        assert sql == ref == {}

    def test_the_whole_case_dict_matches_end_to_end(self, db_cursor):
        """Through `_member_cases_by_cell`, so the observation half and the
        rounding are included rather than assumed to be shared."""
        import flask_api as api
        args = (db_cursor, 'UKMO', 'precipitation', fx.INIT_TIME,
                BOX['min_lat'], BOX['max_lat'], BOX['min_lon'], BOX['max_lon'])
        sql = api._member_cases_by_cell(*args, hours=HOURS)
        ref = api._member_cases_by_cell(*args, hours=HOURS,
                                        _moments=api._member_moments_python)
        assert set(sql) == set(ref) and sql
        for cell, cases in ref.items():
            assert set(sql[cell]) == set(cases)
            for hour, case in cases.items():
                for key, value in case.items():
                    got = sql[cell][hour][key]
                    if isinstance(value, float):
                        assert got == pytest.approx(value, **FLOAT4), \
                            f'{key} at {cell} +{hour}h'
                    else:
                        assert got == value, f'{key} at {cell} +{hour}h'


class TestTheArithmeticTheSqlRestates:
    """Properties the fixture's own conventions pin, so a plausible-looking SQL
    change cannot pass by agreeing with an equally wrong reference."""

    def test_the_cumulative_model_is_differenced_not_read_as_a_total(self, db_cursor):
        """AIFS stores a running total, so hour h holds h/6 times the 6 h
        amount. Read as an amount the rate would climb with lead time; the
        fixture's field is a constant 3.0 mm/h, and getting that back at every
        lead time is only possible if each member was differenced against its
        own predecessor."""
        sql, _ref = _both(db_cursor, 'AIFS', 'precipitation', HOURS)
        wet = (35.0, -76.0)
        hours = sorted(sql[wet])
        assert len(hours) >= 3
        for hour in hours:
            assert sql[wet][hour][0] == pytest.approx(fx.EXPECT_PRECIP['rate'],
                                                      **FLOAT4), f'+{hour}h'
        # And the totals really do grow, so the constant above is a result
        # rather than a property of flat input.
        db_cursor.execute("""
            SELECT forecast_hour, avg(value) AS v FROM regridded_forecast_member
            WHERE model_name = 'AIFS' AND variable_name = 'precipitation'
              AND init_time = %s AND latitude = 35.0 AND longitude = -76.0
            GROUP BY 1 ORDER BY 1
        """, (fx.INIT_TIME,))
        stored = [float(r['v']) for r in db_cursor.fetchall()]
        assert stored == sorted(stored) and stored[-1] > stored[0] * 2

    def test_an_hourly_model_is_pooled_from_six_one_hour_records(self, db_cursor):
        """UKMO's re-binning is the path with no pass-through case: every
        scored record is six hourly records combined, and only a complete six
        may be."""
        sql, _ref = _both(db_cursor, 'UKMO', 'precipitation', HOURS)
        cell = next(iter(sql))
        assert all(h % 6 == 0 and h > 0 for h in sql[cell]), sorted(sql[cell])

    def test_the_spread_is_the_population_one(self, db_cursor):
        """`var_pop`, not `var_samp` — the difference is a factor n/(n-1), which
        is 1.33 on the fixture's four members and would hide inside a tolerance
        on a 50-member run."""
        sql, _ref = _both(db_cursor, 'AIFS', 'wind', set(fx.WIND_HOURS['AIFS']))
        cell = next(iter(sql))
        hour = next(iter(sql[cell]))
        mean, spread_sq, n = sql[cell][hour]
        assert n == len(fx.MEMBER_OFFSETS)
        assert spread_sq == pytest.approx(fx.wind_spread(hour) ** 2, abs=1e-6)
        assert math.sqrt(spread_sq) < fx.wind_spread(hour) * math.sqrt(n / (n - 1))
