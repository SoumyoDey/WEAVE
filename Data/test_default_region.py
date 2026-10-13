"""One default region, and it is the domain the data is on.

The defect (`NEXT_STEPS.md` §69): three endpoints carried their own copy of the
default bounding box and one of them disagreed. `_parse_bbox` and
`/api/compare/spatial-agreement` used 25-45 N / -85..-65 W, the regridded
domain; `/api/region-categorical-metrics` used 20-40 N / -100..-60 W, which
clips 40-45 N off the grid and extends west into cells that hold nothing.

It changed a published score. Same request, with and without a bbox, AIFS
precipitation at 5 mm/6h over 0-168 h of 2025-09-16 00Z:

    endpoint's own default    CSI 0.1602   POD 0.2192   FSS 0.4672
    the shared domain         CSI 0.1473   POD 0.1960   FSS 0.4402

This is `test_verification_defaults`-shaped reasoning applied to the server:
§54 unified the defaults the *client* sends, and could not reach this, because
no frontend test exercises a request the frontend never makes.

**The cross-file assertion is the one that keeps mattering.** Pinning the four
literals only says the API agrees with itself. The risk worth guarding is the
grid moving — a re-regrid onto a different domain — and `DEFAULT_REGION` then
describing a region the data is no longer on, which is §24's defect exactly: a
confident statement about something no longer true.
"""
import ast
import pathlib

import pytest

import flask_api as api


HERE = pathlib.Path(__file__).resolve().parent


def _regrid_constants():
    """`TARGET_LAT_RANGE`/`TARGET_LON_RANGE`, as the loader exposes them.

    **This used to parse `regrid_members.py`'s source text with `ast`**, because
    the loader is a CLI that imports scipy and calls `load_dotenv`, and making
    the API's tests depend on that to compare four numbers was the worse trade.

    §76 removed the need: both sides now read `domain.py`, which imports
    nothing but `os`, so the comparison is between two objects instead of
    between a value and a transcription. The test is kept — it is the
    cross-boundary assertion, and it is now stronger, because it fails if
    either side stops reading the shared module rather than only if the digits
    drift.
    """
    import domain
    return {'TARGET_LAT_RANGE': domain.LAT_RANGE,
            'TARGET_LON_RANGE': domain.LON_RANGE}


def test_the_loader_and_the_api_read_the_same_module():
    # The structural half: not "these numbers agree today" but "there is only
    # one place for them to come from".
    import domain
    import regrid_members as rm
    assert rm.TARGET_LAT_RANGE is domain.LAT_RANGE
    assert rm.TARGET_LON_RANGE is domain.LON_RANGE
    assert rm.TARGET_RESOLUTION == domain.RESOLUTION


def test_the_parse_found_the_constants():
    got = _regrid_constants()
    assert set(got) == {'TARGET_LAT_RANGE', 'TARGET_LON_RANGE'}, got


def test_default_region_is_the_regridded_domain():
    g = _regrid_constants()
    assert (api.DEFAULT_REGION['min_lat'], api.DEFAULT_REGION['max_lat']) == g['TARGET_LAT_RANGE']
    assert (api.DEFAULT_REGION['min_lon'], api.DEFAULT_REGION['max_lon']) == g['TARGET_LON_RANGE']


def test_parse_bbox_defaults_to_it():
    bbox, err = api._parse_bbox({})
    assert err is None
    assert bbox == api.DEFAULT_REGION


@pytest.mark.parametrize('payload_key', ['min_lat', 'max_lat', 'min_lon', 'max_lon'])
def test_each_bound_is_independently_defaulted(payload_key):
    # A partial bbox must fill the rest from the shared region rather than
    # falling back to a whole other box.
    bbox, err = api._parse_bbox({payload_key: api.DEFAULT_REGION[payload_key]})
    assert err is None
    assert bbox == api.DEFAULT_REGION


def test_no_endpoint_keeps_its_own_copy_of_the_domain():
    """No bare bbox literals left in the source.

    The scan, not the three call sites, is what stops a fourth copy appearing:
    the defect was never that one number was wrong, it was that the number was
    written down in more than one place.
    """
    src = (HERE / 'flask_api.py').read_text()
    tree = ast.parse(src)
    offenders = []
    for node in ast.walk(tree):
        # `something.get('min_lat', <literal>)` — the shape all three copies had.
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and node.func.attr == 'get' and len(node.args) == 2):
            continue
        key = node.args[0]
        if not (isinstance(key, ast.Constant) and key.value in
                ('min_lat', 'max_lat', 'min_lon', 'max_lon')):
            continue
        default = node.args[1]
        # A literal (or a negated literal) is a second copy; a Subscript into
        # DEFAULT_REGION is the shared one.
        if isinstance(default, ast.Constant) or (
                isinstance(default, ast.UnaryOp) and isinstance(default.operand, ast.Constant)):
            offenders.append((key.value, node.lineno))
    assert offenders == [], (
        'bbox defaults written as literals instead of DEFAULT_REGION: '
        + ', '.join(f'{k} at line {ln}' for k, ln in offenders))
