"""Tests for the precipitation scaling stage, `scale_precip.py`.

No database. What is pinned is the arithmetic of each rule, the registry label
each rule implies, and the refusals. A wrong divisor is not a crash. It is a
precipitation field off by up to 2x that nobody would question.
"""
import json

import pytest

import run_registry as reg
import scale_precip as sp


def _write(directory, name, records):
    directory.mkdir(parents=True, exist_ok=True)
    (directory / name).write_text(json.dumps(records))


def _name(model, hour, member=1):
    return f'conus_east_20250916000000-{hour}h-{model.lower()}_precipitation_member_{member}.json'


POINT = [{'lat': 35.0, 'lon': -75.0, 'value': 1.2}]


class TestTheWindowEachRuleDividesBy:
    def test_flat_divides_aifs_by_six_at_every_hour(self):
        assert {sp.record_window_hours('AIFS', h) for h in (6, 9, 12, 360)} == {6.0}

    def test_flat_divides_gefs_by_three_at_every_hour(self):
        """The legacy rule the loaded GEFS run carries. Scoring undoes it with
        period / divisor, so the 6-hour buckets come out right downstream."""
        assert {sp.record_window_hours('GEFS', h) for h in (3, 6, 9, 12)} == {3.0}

    def test_per_window_follows_the_gefs_bucket_reset(self):
        assert sp.record_window_hours('GEFS', 3, sp.PER_WINDOW) == 3.0
        assert sp.record_window_hours('GEFS', 6, sp.PER_WINDOW) == 6.0
        assert sp.record_window_hours('GEFS', 9, sp.PER_WINDOW) == 3.0
        assert sp.record_window_hours('GEFS', 12, sp.PER_WINDOW) == 6.0

    def test_per_window_is_still_six_for_cumulative_aifs(self):
        assert sp.record_window_hours('AIFS', 12, sp.PER_WINDOW) == 6.0

    def test_ukmo_is_refused_because_it_never_passes_through_here(self):
        with pytest.raises(sp.ScalingError, match='UKMO'):
            sp.record_window_hours('UKMO', 6)

    def test_an_unknown_rule_is_refused(self):
        with pytest.raises(sp.ScalingError):
            sp.record_window_hours('GEFS', 6, 'fixed')


class TestTheRegistryLabelEachRuleImplies:
    def test_the_default_rule_is_what_the_registry_already_declares(self):
        """So a run scaled with no flags needs no registry step beyond
        --backfill. If this fails, the default and DECLARED have drifted and
        every new load is mislabelled."""
        for model in sp.MODELS:
            assert sp.registry_convention(model) == reg.DECLARED[(model, 'precipitation')]

    def test_the_flat_divisors_are_the_scoring_fallback_constant(self):
        """`_export_divisor` falls back to this constant when the registry
        cannot answer, so it must describe what the default rule writes."""
        from metrics import SCALED_EXPORT_DIVISOR_HOURS
        assert sp.FLAT_DIVISOR_HOURS == SCALED_EXPORT_DIVISOR_HOURS

    def test_per_window_gefs_must_be_recorded_as_rate(self):
        assert sp.registry_convention('GEFS', sp.PER_WINDOW) == (reg.RATE, None)

    def test_per_window_aifs_keeps_its_scaled_label(self):
        assert sp.registry_convention('AIFS', sp.PER_WINDOW) == (reg.SCALED, 6.0)

    def test_every_label_is_one_the_registry_accepts(self):
        """record() refuses incoherent pairs such as `rate` with a divisor; none
        of the labels this stage prints may be one of them."""
        from unittest.mock import MagicMock
        for model in sp.MODELS:
            for rule in sp.RULES:
                convention, divisor = sp.registry_convention(model, rule)
                reg.record(MagicMock(), model, 'precipitation', '2025-09-16 00:00:00',
                           convention=convention, export_divisor_h=divisor)


class TestScalingADirectory:
    def test_values_are_divided_and_rounded(self, tmp_path):
        _write(tmp_path / 'in', _name('GEFS', 6), [{'lat': 35.0, 'lon': -75.0, 'value': 1.0}])
        sp.scale_directory(tmp_path / 'in', tmp_path / 'out', 'GEFS', sp.PER_WINDOW, 4)
        out = json.loads((tmp_path / 'out' / _name('GEFS', 6)).read_text())
        assert out == [{'lat': 35.0, 'lon': -75.0, 'value': 0.1667}]

    def test_three_decimals_reproduces_the_legacy_gefs_export(self, tmp_path):
        """The loaded GEFS run is round(round(tp, 3) / 3, 3). The converter does
        the inner round; --decimals 3 is the outer one."""
        _write(tmp_path / 'in', _name('GEFS', 6), [{'lat': 35.0, 'lon': -75.0, 'value': 2.345}])
        sp.scale_directory(tmp_path / 'in', tmp_path / 'out', 'GEFS', sp.FLAT, 3)
        out = json.loads((tmp_path / 'out' / _name('GEFS', 6)).read_text())
        assert out[0]['value'] == round(2.345 / 3, 3)

    def test_the_summary_says_which_divisor_hit_which_files(self, tmp_path):
        for hour in (3, 6, 9, 12):
            _write(tmp_path / 'in', _name('GEFS', hour), POINT)
        summary = sp.scale_directory(tmp_path / 'in', tmp_path / 'out', 'GEFS', sp.PER_WINDOW)
        assert summary['files_written'] == 4
        assert summary['divisors'] == {'h%6==0': {'divide_by_h': 6.0, 'files': 2},
                                       'h%6==3': {'divide_by_h': 3.0, 'files': 2}}

    def test_a_file_with_no_hour_is_skipped_not_guessed(self, tmp_path):
        _write(tmp_path / 'in', 'gefs_precipitation_f006.json', POINT)
        _write(tmp_path / 'in', _name('GEFS', 6), POINT)
        summary = sp.scale_directory(tmp_path / 'in', tmp_path / 'out', 'GEFS')
        assert summary['files_written'] == 1
        assert [s['file'] for s in summary['skipped']] == ['gefs_precipitation_f006.json']
        assert not (tmp_path / 'out' / 'gefs_precipitation_f006.json').exists()

    def test_the_output_carries_a_marker_naming_the_registry_label(self, tmp_path):
        _write(tmp_path / 'in', _name('GEFS', 6), POINT)
        sp.scale_directory(tmp_path / 'in', tmp_path / 'out', 'GEFS', sp.PER_WINDOW)
        marker = json.loads((tmp_path / 'out' / sp.MARKER).read_text())
        assert marker['registry'] == {'export_convention': reg.RATE, 'export_divisor_h': None}


class TestTheRefusals:
    def test_an_already_scaled_directory_is_not_scaled_twice(self, tmp_path):
        _write(tmp_path / 'in', _name('AIFS', 6), POINT)
        sp.scale_directory(tmp_path / 'in', tmp_path / 'once', 'AIFS')
        with pytest.raises(sp.ScalingError, match='already scaled'):
            sp.scale_directory(tmp_path / 'once', tmp_path / 'twice', 'AIFS')

    def test_scaling_in_place_is_refused(self, tmp_path):
        _write(tmp_path / 'in', _name('AIFS', 6), POINT)
        with pytest.raises(sp.ScalingError, match='same directory'):
            sp.scale_directory(tmp_path / 'in', tmp_path / 'in', 'AIFS')

    def test_an_empty_directory_is_refused(self, tmp_path):
        (tmp_path / 'in').mkdir()
        with pytest.raises(sp.ScalingError, match='no JSON'):
            sp.scale_directory(tmp_path / 'in', tmp_path / 'out', 'AIFS')


class TestTheCommandLine:
    def test_per_window_gefs_prints_the_registry_step(self, tmp_path, capsys):
        _write(tmp_path / 'in', _name('GEFS', 6), POINT)
        code = sp.main(['--model', 'gefs', '--rule', 'per-window',
                        '--source', str(tmp_path / 'in'), '--out', str(tmp_path / 'out')])
        assert code == 0
        assert '--convention rate' in capsys.readouterr().out

    def test_a_refusal_exits_non_zero(self, tmp_path):
        (tmp_path / 'in').mkdir()
        assert sp.main(['--model', 'AIFS', '--source', str(tmp_path / 'in'),
                        '--out', str(tmp_path / 'out')]) == 1

    def test_skipped_files_exit_with_their_own_code(self, tmp_path):
        _write(tmp_path / 'in', 'no_hour.json', POINT)
        _write(tmp_path / 'in', _name('AIFS', 6), POINT)
        assert sp.main(['--model', 'AIFS', '--source', str(tmp_path / 'in'),
                        '--out', str(tmp_path / 'out')]) == 2
