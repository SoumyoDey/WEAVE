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


# ── Against real SQL, in the fixture database ─────────────────────────────────
#
# These used to take a `client` fixture of their own: it checked that
# `api.DB_CONFIG` was reachable, skipped if not, and then returned
# `api.app.test_client()`. **That tested nothing — and not only in CI.**
#
# `conftest.py` replaces `psycopg2.pool.ThreadedConnectionPool` with a MagicMock
# before `flask_api` is imported, so `api.connection_pool` is a mock unless a
# fixture replaces it. The old `client` never did. `get_db_connection()`
# therefore handed the endpoints a mock cursor, and a MagicMock iterates empty,
# so every request below returned `[]` with status 200 — and every assertion
# passed on it. "Not truncated" is true of an empty list; `len([]) <= 5` is
# true; the prefix comparison was `[] == []`; and the one branch that checked
# `X-Truncated` was guarded by an `if` that never fired. The reachability check
# was theatre: it proved a server was up and then never spoke to it.
#
# So this is **not** the `test_run_registry.py` problem (§26 — real tests that
# skipped in CI). It is the Traps list entry itself — *a refactor can hollow out
# a test instead of failing it* — and it was green on every machine, which is
# exactly why nothing pointed at it. The CI skips were the visible 9; the
# invisible 9 were the same tests passing locally while asserting nothing.
#
# conftest's `db_client` is the fixture that actually points the endpoints at a
# database: it monkeypatches `api.connection_pool` to a real pool on the fixture
# database. UKMO is seeded there on its own native grid, so these now run real
# SQL, and a low limit genuinely bites. The first test below asserts that before
# any of the others read through it.


class TestTheDefaultCapClearsTheRealWorstCase:
    """What `test_todays_data_is_not_truncated` was actually for.

    That test meant to guard one thing: the shipped cap is above anything the
    loaded data produces, so it changes no behaviour today. That is a claim
    about a constant and a measurement, not about a query — and stating it
    without a database is what makes it true everywhere instead of nowhere.
    The fixture cannot carry it, because the fixture's domain is a 5x5 patch
    and would clear any plausible cap.
    """

    # UKMO wind on the loaded run: 7,597 native cells and 946 KB, the figure
    # `flask_api.POINT_LIST_MAX_CELLS` is set against. Restated here rather than
    # imported, so the cap and the worst case it answers cannot move together
    # silently.
    MEASURED_WORST_CASE_CELLS = 7597

    def test_the_cap_is_above_the_measured_worst_case(self):
        assert api.POINT_LIST_MAX_CELLS > self.MEASURED_WORST_CASE_CELLS, (
            f'the cap ({api.POINT_LIST_MAX_CELLS}) is at or below the measured '
            f'worst case ({self.MEASURED_WORST_CASE_CELLS}), so today\'s data '
            f'is being silently truncated')

    def test_it_clears_it_with_room_for_the_domain_to_grow(self):
        # Not a round-number preference: the cap exists for the case nobody has
        # loaded yet, so it has to clear the known worst case by enough that a
        # finer model does not reach it the same week.
        assert api.POINT_LIST_MAX_CELLS >= 2 * self.MEASURED_WORST_CASE_CELLS


class TestAgainstTheFixtureData:
    """The cap must be inert on a normal response and bite when lowered."""

    URLS = [
        '/api/forecast-data?model=UKMO&variable=precipitation&hour=6&member=mean',
        '/api/wind-data?model=UKMO&variable=wind&hour=6&member=mean',
        '/api/wind-data?model=UKMO&variable=wind&hour=6&member=std',
        '/api/wind-data?model=UKMO&variable=wind&hour=6&member=0',
    ]

    LOW_LIMIT = 5

    def test_every_url_returns_more_cells_than_the_low_limit(self, db_client):
        """The non-emptiness guard, asserted before anything reads through it.

        This is the test the old module most needed and did not have. Every
        assertion below is satisfied by an empty response, so without this the
        whole class goes green against a fixture that serves nothing — which is
        precisely the state it was in for its entire existence. It must also be
        *more* than `LOW_LIMIT`, or "a low limit bites" would be vacuous for a
        different reason.
        """
        counts = {}
        for url in self.URLS:
            r = db_client.get(url)
            assert r.status_code == 200, (url, r.status_code, r.get_data(as_text=True)[:200])
            body = r.get_json()
            assert isinstance(body, list), (url, type(body))
            counts[url] = len(body)
        too_few = {u: n for u, n in counts.items() if n <= self.LOW_LIMIT}
        assert too_few == {}, (
            f'these returned {self.LOW_LIMIT} cells or fewer, so the cap tests '
            f'below would pass without the cap ever being reached: {too_few}')

    @pytest.mark.parametrize('url', URLS)
    def test_a_normal_response_is_not_truncated(self, db_client, url):
        # The default cap is far above the fixture's domain, so a response here
        # must come back whole. A truncation flag on a 70-cell patch would mean
        # the cap is being applied where it should be inert.
        r = db_client.get(url)
        assert r.status_code == 200
        assert 'X-Truncated' not in r.headers, (
            f'{url} is being truncated at the default limit '
            f'({api.POINT_LIST_MAX_CELLS})')
        assert r.headers['X-Row-Limit'] == str(api.POINT_LIST_MAX_CELLS)

    @pytest.mark.parametrize('url', URLS)
    def test_a_low_limit_bites_and_is_reported(self, db_client, url, monkeypatch):
        # Proves the cap is wired to each branch rather than only to the one
        # that happened to be tested — the std branch was missed on the first
        # pass and only a per-branch check found it. The truncation is now
        # asserted outright; it used to sit behind an `if` that never fired,
        # because the response was always empty.
        monkeypatch.setattr(api, 'POINT_LIST_MAX_CELLS', self.LOW_LIMIT)
        r = db_client.get(url)
        assert r.status_code == 200
        body = r.get_json()
        assert len(body) == self.LOW_LIMIT, (
            f'{url} returned {len(body)} cells for a limit of {self.LOW_LIMIT}')
        assert r.headers['X-Truncated'] == 'true', (
            f'{url} was trimmed to {self.LOW_LIMIT} cells without saying so')
        assert r.headers['X-Row-Limit'] == str(self.LOW_LIMIT)
        assert r.headers['X-Row-Count'] == str(self.LOW_LIMIT)
        # The promise this cap exists for: whole cells, never a partial series.
        assert 'X-Total-Cells' not in r.headers

    def test_the_capped_rows_are_a_prefix_of_the_uncapped_ones(self, db_client,
                                                               monkeypatch):
        # Truncation should drop the tail, not resample: the first N cells of a
        # capped response must match the first N of a full one.
        url = self.URLS[1]
        full = db_client.get(url).get_json()
        assert len(full) > self.LOW_LIMIT, 'nothing to truncate'
        monkeypatch.setattr(api, 'POINT_LIST_MAX_CELLS', self.LOW_LIMIT)
        capped = db_client.get(url).get_json()
        assert len(capped) == self.LOW_LIMIT
        key = lambda p: (p['lat'], p['lon'])
        assert [key(p) for p in capped] == [key(p) for p in full[:len(capped)]]
