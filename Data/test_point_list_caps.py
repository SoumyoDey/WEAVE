"""Row caps on the point-list endpoints.

`/api/forecast-data` and `/api/wind-data` return one record per native grid cell,
and the native grid is a property of whatever data was loaded rather than of
anything the request controls. Today's worst case is UKMO wind: 7,597 cells and
946 KB. A finer model or a wider domain grows that without limit and no
parameter bounds it.

Two properties matter more than the cap itself:

- **It trims whole cells.** `/api/forecast-data` queries one row per (cell, hour)
  and groups into cells afterwards, so a plain `LIMIT` on rows would cut the last
  cell in half and return a cell whose value was computed from a partial series —
  a subtly wrong number rather than a visibly short list. The wrong failure.
- **Truncation is reported.** A silently shortened map looks complete. These
  endpoints return a bare JSON array, so the shape cannot carry a flag without
  breaking every caller for the common case; it goes in headers, and is logged
  server-side as well.
"""
import os

import pytest

import flask_api as api


class TestCapCells:
    """The trim itself: whole cells, deterministic, and inert under the limit."""

    def _cells(self, n):
        # Deliberately not in sorted order, so a trim that forgets to sort is
        # visible rather than accidentally right.
        return {(35.0 + i * 0.5, -75.0): {6: float(i)}
                for i in reversed(range(n))}

    def test_under_the_limit_nothing_is_touched(self):
        by_cell = self._cells(10)
        kept, truncated = api._cap_cells(by_cell, limit=100)
        assert truncated is False
        assert kept == by_cell

    def test_exactly_at_the_limit_is_not_truncation(self):
        # An off-by-one here would report every full-domain request as truncated.
        by_cell = self._cells(50)
        kept, truncated = api._cap_cells(by_cell, limit=50)
        assert truncated is False
        assert len(kept) == 50

    def test_over_the_limit_trims_and_says_so(self):
        by_cell = self._cells(60)
        kept, truncated = api._cap_cells(by_cell, limit=50)
        assert truncated is True
        assert len(kept) == 50

    def test_the_survivors_are_deterministic(self):
        # Without sorting, which cells survive depends on dict insertion order,
        # so two identical requests could return different halves of the domain —
        # and the cache would key them identically.
        a, _ = api._cap_cells(self._cells(60), limit=10)
        b, _ = api._cap_cells(self._cells(60), limit=10)
        assert list(a) == list(b)
        assert list(a) == sorted(a)

    def test_whole_cells_only(self):
        # The point of trimming after grouping: every surviving cell keeps its
        # complete hour series.
        by_cell = {(35.0 + i * 0.5, -75.0): {6: 1.0, 12: 2.0, 18: 3.0}
                   for i in range(60)}
        kept, _ = api._cap_cells(by_cell, limit=10)
        assert all(set(series) == {6, 12, 18} for series in kept.values())

    def test_the_default_limit_is_the_configured_one(self):
        by_cell = self._cells(3)
        assert api._cap_cells(by_cell)[1] is False
        assert api.POINT_LIST_MAX_CELLS >= 1


class TestTheResponseReportsTruncation:
    def test_an_untruncated_response_says_the_count_and_the_limit(self):
        with api.app.test_request_context('/'):
            r = api._point_list_response([{'lat': 1, 'lon': 2}], False)
        assert r.headers['X-Row-Count'] == '1'
        assert r.headers['X-Row-Limit'] == str(api.POINT_LIST_MAX_CELLS)
        assert 'X-Truncated' not in r.headers

    def test_a_truncated_response_says_so_without_inventing_a_total(self):
        with api.app.test_request_context('/'):
            r = api._point_list_response([{'lat': 1}], True)
        assert r.headers['X-Truncated'] == 'true'
        assert r.headers['X-Row-Count'] == '1'
        assert r.headers['X-Row-Limit'] == str(api.POINT_LIST_MAX_CELLS)
        # No "showing N of M". The query reads limit+1 rows so overflow is
        # detectable cheaply, which means the only total available is limit+1 —
        # an earlier version reported that and said "100 of 101" for a request
        # whose real total was 7,597. Worse than silence.
        assert 'X-Total-Cells' not in r.headers

    def test_the_body_stays_a_bare_array(self):
        # The shape is the contract: the frontend reads the response as a list.
        # Reporting an edge case must not break the common case.
        with api.app.test_request_context('/'):
            r = api._point_list_response([{'lat': 1}, {'lat': 2}], True)
        assert isinstance(r.get_json(), list)
        assert len(r.get_json()) == 2


# ── Against the real database ─────────────────────────────────────────────────

def _skip_reason():
    if os.environ.get('WEAVE_SKIP_DB_TESTS'):
        return 'WEAVE_SKIP_DB_TESTS is set'
    try:
        import psycopg2
        psycopg2.connect(**{k: v for k, v in api.DB_CONFIG.items()}).close()
    except Exception as exc:                                  # pragma: no cover
        return f'no database: {type(exc).__name__}'
    return None


@pytest.fixture
def client():
    reason = _skip_reason()
    if reason:
        pytest.skip(reason)
    api.app.config['TESTING'] = True
    return api.app.test_client()


class TestAgainstTheLoadedData:
    """The cap must be inert on today's data and bite when lowered."""

    URLS = [
        '/api/forecast-data?model=UKMO&variable=precipitation&hour=6&member=mean',
        '/api/wind-data?model=UKMO&variable=wind&hour=6&member=mean',
        '/api/wind-data?model=UKMO&variable=wind&hour=6&member=std',
        '/api/wind-data?model=UKMO&variable=wind&hour=6&member=0',
    ]

    @pytest.mark.parametrize('url', URLS)
    def test_todays_data_is_not_truncated(self, client, url):
        # The cap is set well above the current worst case on purpose, so it
        # changes no behaviour now. If this fails, the limit is too low for the
        # loaded data and someone is silently getting a partial map.
        r = client.get(url)
        assert r.status_code == 200
        assert 'X-Truncated' not in r.headers, (
            f'{url} is being truncated at the default limit '
            f'({api.POINT_LIST_MAX_CELLS})')

    @pytest.mark.parametrize('url', URLS)
    def test_a_low_limit_bites_and_is_reported(self, client, url, monkeypatch):
        # Proves the cap is wired to each branch rather than only to the one
        # that happened to be tested — the std branch was missed on the first
        # pass and only a per-branch check found it.
        monkeypatch.setattr(api, 'POINT_LIST_MAX_CELLS', 5)
        r = client.get(url)
        assert r.status_code == 200
        body = r.get_json()
        assert len(body) <= 5, f'{url} returned {len(body)} rows for a limit of 5'
        if r.headers.get('X-Truncated') == 'true':
            assert r.headers['X-Row-Limit'] == '5'

    def test_the_capped_rows_are_a_prefix_of_the_uncapped_ones(self, client, monkeypatch):
        # Truncation should drop the tail, not resample: the first N cells of a
        # capped response must match the first N of a full one.
        url = self.URLS[1]
        full = client.get(url).get_json()
        monkeypatch.setattr(api, 'POINT_LIST_MAX_CELLS', 5)
        capped = client.get(url).get_json()
        assert len(capped) <= 5
        key = lambda p: (p['lat'], p['lon'])
        assert [key(p) for p in capped] == [key(p) for p in full[:len(capped)]]
