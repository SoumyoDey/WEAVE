"""Every rate conversion reads the run's divisor, not the module constant.

`SCALED_EXPORT_DIVISOR_HOURS` describes how the *currently loaded* export was
produced. The authority is `forecast_run_registry.export_divisor_h`, written at
load time, because a re-export can change the convention for one run and leave
every other run alone — which is why phase 4 moved it into the registry
(`NEXT_STEPS.md` §72).

Twelve call sites passed `exported=_export_divisor(...)`. Two did not: the
member branch of `/api/forecast-data` (the map overlay) and
`/api/point-timeseries` (the cone of uncertainty). Both silently read the
constant.

**Nothing was wrong when this was found**, and that is the part worth keeping:
all 17 loaded run/variable rows agreed with the constant, so the two wrong
branches and the ten right ones returned identical numbers. The defect was
invisible by construction, and would have become a map disagreeing with the
scores beside it on the first re-export that differed.

Two kinds of test, because neither is sufficient alone:

* **Behavioural** — make the registry's answer differ from the constant and
  watch the endpoint's numbers follow. A source scan cannot show that the value
  reaches the arithmetic.
* **Structural** — no call site may omit `exported=`. This is what stops a
  *thirteenth* site appearing, because the defect was never one wrong number;
  it was a default that applies silently whenever a caller forgets.

Neither endpoint caches its response, so calling one twice in a test really
does recompute it.
"""
import ast
import inspect
import pathlib

import pytest

import fixture_db as fx
import flask_api as api
import metrics


HERE = pathlib.Path(__file__).resolve().parent
APPROX = {'rel': 1e-6}

# UKMO stores a rate natively and records no divisor, so it is the control:
# whatever the registry says, there is nothing to divide.
NO_DIVISOR = 'UKMO'
CUMULATIVE = [m for m in fx.MODELS if m != NO_DIVISOR]


def _double_the_divisor(monkeypatch):
    """Make the registry disagree with the constant by exactly 2x.

    `_export_divisor` is patched rather than the fixture's registry row so the
    test stays about *wiring* — does this branch consult the per-run value at
    all — rather than about the loader, which `test_run_registry.py` covers.
    """
    real = api._export_divisor

    def doubled(model_name, init_time, variable='precipitation'):
        got = real(model_name, init_time, variable)
        return None if got is None else got * 2

    monkeypatch.setattr(api, '_export_divisor', doubled)


def _map_member_values(client, model):
    pts = client.get(f'/api/forecast-data?model={model}&hour=6&member=0').get_json()
    return sorted(p['value'] for p in pts if fx.outcome(p['lat']) != 'miss')


def _cone_means(client, model):
    body = client.get(f'/api/point-timeseries?model={model}&variable=precipitation'
                      '&lat=36.18&lon=-75.515625&radius=0.2').get_json()
    return [r['mean'] for r in body]


class TestTheValueReachesTheArithmetic:
    """Before/after on the two branches that used to read the constant."""

    @pytest.mark.parametrize('model', CUMULATIVE)
    def test_the_map_member_branch_follows_the_registry(self, db_client, monkeypatch, model):
        before = _map_member_values(db_client, model)
        assert before, f'{model}: no wet cells to compare'

        _double_the_divisor(monkeypatch)
        after = _map_member_values(db_client, model)

        # `_increment_divisor` is `period / exported`, so the rate is
        # proportional to `exported`: twice the recorded divisor, twice the
        # rate. (I asserted "half" first and the test caught it.)
        assert after == pytest.approx([v * 2 for v in before], **APPROX)

    @pytest.mark.parametrize('model', CUMULATIVE)
    def test_the_cone_follows_the_registry(self, db_client, monkeypatch, model):
        before = _cone_means(db_client, model)
        assert before, f'{model}: no series to compare'

        _double_the_divisor(monkeypatch)
        after = _cone_means(db_client, model)

        assert after == pytest.approx([v * 2 for v in before], **APPROX)

    def test_a_model_with_no_divisor_does_not_move(self, db_client, monkeypatch):
        """Without this, code that halved everything unconditionally would pass.

        UKMO records no `export_divisor_h`, so doubling "the divisor" must
        change nothing at all on either endpoint.
        """
        map_before, cone_before = (_map_member_values(db_client, NO_DIVISOR),
                                   _cone_means(db_client, NO_DIVISOR))
        assert map_before and cone_before

        _double_the_divisor(monkeypatch)

        assert _map_member_values(db_client, NO_DIVISOR) == pytest.approx(map_before, **APPROX)
        assert _cone_means(db_client, NO_DIVISOR) == pytest.approx(cone_before, **APPROX)


class TestNoCallSiteOmitsIt:
    """The structural guard — what stops a thirteenth site appearing."""

    @staticmethod
    def _calls_missing_exported():
        """Real call sites, found with `ast`.

        A text scan flagged a docstring line that merely *names* the helper, so
        it is parsed instead: only `Call` nodes count, and only a real
        `exported=` keyword satisfies them.
        """
        tree = ast.parse((HERE / 'flask_api.py').read_text())
        out = []
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            fn = node.func
            name = fn.id if isinstance(fn, ast.Name) else getattr(fn, 'attr', None)
            if name not in ('_precip_rate_series', '_precip_member_rate_series'):
                continue
            if not any(k.arg == 'exported' for k in node.keywords):
                out.append(node.lineno)
        return sorted(out)

    def test_the_scan_finds_the_calls_at_all(self):
        # Guards against passing vacuously on a renamed helper, the way §32's
        # JS parser asserts it parsed something before comparing.
        tree = ast.parse((HERE / 'flask_api.py').read_text())
        found = sum(
            1 for n in ast.walk(tree)
            if isinstance(n, ast.Call)
            and (n.func.id if isinstance(n.func, ast.Name) else getattr(n.func, 'attr', None))
            in ('_precip_rate_series', '_precip_member_rate_series'))
        assert found >= 10, f'only {found} call sites found — was the helper renamed?'

    def test_no_call_site_falls_back_to_the_constant(self):
        missing = self._calls_missing_exported()
        assert missing == [], (
            'these calls omit `exported=` and so read SCALED_EXPORT_DIVISOR_HOURS '
            f'instead of the run registry: lines {missing}')


def test_the_constant_stays_available_as_a_default():
    """Deleting the default would be the other way to fix this, and it is wrong.

    `metrics.py` is importable without a database and its unit tests call these
    helpers directly, where there is no run to ask. The fix is that every
    *endpoint* passes the run's value, not that the fallback stops existing.
    """
    for fn in (metrics._precip_member_rate_series, metrics._precip_rate_series):
        assert inspect.signature(fn).parameters['exported'].default is metrics.FROM_CONSTANT
