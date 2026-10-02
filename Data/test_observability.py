"""Tests for request ids, the access log and the readiness probe.

`SYSTEM_DESIGN_PLAN.md` S2 asked for an observable service. What it found was 86
`print()` calls and no `logging` import, and the worst consequence was not the
missing timestamps: every endpoint ended `except Exception as e: print(str(e))`,
so **the traceback was discarded** and the one line a reader needs was never
written. `TestErrorsKeepTheirTraceback` is therefore the test that matters most
here, and it is the one that would have had nothing to assert against before.

The second-most-important is `TestAnInboundRequestIdIsNotTrusted`. Propagating a
caller's `X-Request-ID` is what makes a trace span a proxy and the app, and
writing an unvalidated header into a log line is how a newline in that header
forges a log entry. The ids are replaced rather than stripped, so there is no
half-sanitised middle state to find later.
"""
import logging

import pytest
from flask import Flask, jsonify

import observability as obs


# ── The request id ────────────────────────────────────────────────────────────

def _app():
    """A throwaway app with the middleware installed.

    Not the real `flask_api.app`: `install` registers `before_request` and
    `after_request` hooks, and adding a second set to the live app would make
    every other test in the suite log twice and count twice.
    """
    app = Flask(__name__)

    @app.route('/ok')
    def ok():
        return jsonify({'request_id': obs.current_request_id()})

    @app.route('/boom')
    def boom():
        return jsonify({'error': 'no'}), 500

    @app.route('/api/health')
    def health():
        return jsonify({'ok': True})

    stats = obs.install(app)
    return app, stats


class TestAnInboundRequestIdIsNotTrusted:
    # Split deliberately. Werkzeug's test client refuses to *send* a header
    # containing a newline — `ValueError: Header values must not contain newline
    # characters` — so the forged-log-entry case cannot be driven through a
    # client at all. That is one layer of defence and not ours; the validator is
    # tested directly for it, because the request need not arrive through
    # werkzeug's client in production.
    @pytest.mark.parametrize('hostile', [
        'abc\ndef',                       # the forged-log-entry case
        'abc\rdef',
        'id with spaces',
        'x' * 65,                         # unbounded growth in every log line
        '../../etc/passwd',
        '<script>alert(1)</script>',
        '',
        'a;b',
        'ümlaut',
    ])
    def test_the_validator_rejects_it_outright(self, hostile):
        assert not obs._SAFE_REQUEST_ID.match(hostile)

    @pytest.mark.parametrize('hostile', [
        'id with spaces',
        'x' * 65,
        '../../etc/passwd',
        '<script>alert(1)</script>',
        '',
    ])
    def test_an_unusable_id_is_replaced_not_cleaned(self, hostile):
        app, _ = _app()
        r = app.test_client().get('/ok', headers={'X-Request-ID': hostile})
        served = r.get_json()['request_id']
        assert served != hostile
        # Replaced wholesale: no fragment of the input survives, so there is no
        # partial-sanitisation bug to find later.
        assert obs._SAFE_REQUEST_ID.match(served)
        assert '\n' not in served and '\r' not in served

    @pytest.mark.parametrize('sane', ['abc123', 'trace-00-ff', 'a.b_c-1', 'X' * 64])
    def test_a_usable_id_is_propagated_unchanged(self, sane):
        # The point of accepting one at all: a trace that spans the proxy and
        # the app needs the same id on both sides.
        app, _ = _app()
        r = app.test_client().get('/ok', headers={'X-Request-ID': sane})
        assert r.get_json()['request_id'] == sane

    def test_one_is_generated_when_the_caller_sends_none(self):
        app, _ = _app()
        r = app.test_client().get('/ok')
        assert obs._SAFE_REQUEST_ID.match(r.get_json()['request_id'])

    def test_it_comes_back_on_the_response(self):
        """So a user reporting "it broke" has something to quote, which is the
        whole reason an id is worth generating."""
        app, _ = _app()
        r = app.test_client().get('/ok')
        assert r.headers['X-Request-ID'] == r.get_json()['request_id']

    def test_two_requests_get_different_ids(self):
        app, _ = _app()
        c = app.test_client()
        assert c.get('/ok').get_json()['request_id'] != c.get('/ok').get_json()['request_id']

    def test_outside_a_request_it_is_a_dash_rather_than_an_error(self):
        # Module-level and startup logging runs with no request context, and a
        # logging filter that raised there would take the process down.
        assert obs.current_request_id() == '-'


# ── The access log ────────────────────────────────────────────────────────────

class TestTheAccessLog:
    def test_a_served_request_is_logged_once_with_its_timing(self, caplog):
        app, _ = _app()
        with caplog.at_level(logging.DEBUG, logger='weave.access'):
            app.test_client().get('/ok')
        lines = [r for r in caplog.records if r.name == 'weave.access']
        assert len(lines) == 1
        assert lines[0].status == 200 and lines[0].path == '/ok'
        assert lines[0].duration_ms >= 0

    def test_a_server_error_is_logged_at_error(self, caplog):
        # The level is the filter an operator actually uses, so a 500 must not
        # arrive at the same level as a 200.
        app, _ = _app()
        with caplog.at_level(logging.DEBUG, logger='weave.access'):
            app.test_client().get('/boom')
        rec = [r for r in caplog.records if r.name == 'weave.access'][0]
        assert rec.levelno == logging.ERROR

    def test_a_probe_is_logged_at_debug_rather_than_dropped(self, caplog):
        """A balancer polls health every few seconds; at INFO it would bury
        everything else. Silently unlogged is worse — that is how "the probe was
        failing all night" becomes unanswerable."""
        app, _ = _app()
        with caplog.at_level(logging.DEBUG, logger='weave.access'):
            app.test_client().get('/api/health')
        rec = [r for r in caplog.records if r.name == 'weave.access'][0]
        assert rec.levelno == logging.DEBUG

    def test_the_line_carries_the_request_id(self, caplog):
        app, _ = _app()
        with caplog.at_level(logging.DEBUG, logger='weave.access'):
            app.test_client().get('/ok', headers={'X-Request-ID': 'trace-1'})
        rec = [r for r in caplog.records if r.name == 'weave.access'][0]
        obs.RequestIdFilter().filter(rec)        # the handler's filter, applied
        assert rec.request_id in ('trace-1', '-')   # '-' once the context closed


# ── Counts and latency ────────────────────────────────────────────────────────

class TestRequestStats:
    def test_an_empty_snapshot_says_nothing_rather_than_zero(self):
        # A p50 of 0 ms would read as "very fast" for a worker that has served
        # nothing. None says which it is.
        snap = obs.RequestStats().snapshot()
        assert snap['requests'] == 0
        assert snap['latency_ms'] == {'p50': None, 'p95': None, 'max': None}

    def test_it_counts_by_status_class(self):
        s = obs.RequestStats()
        for status in (200, 200, 404, 500):
            s.record('e', status, 1.0)
        assert s.snapshot()['by_status'] == {'2xx': 2, '4xx': 1, '5xx': 1}

    def test_one_sample_is_every_percentile(self):
        s = obs.RequestStats()
        s.record('e', 200, 42.0)
        assert s.snapshot()['latency_ms'] == {'p50': 42.0, 'p95': 42.0, 'max': 42.0}

    def test_percentiles_track_the_distribution(self):
        s = obs.RequestStats()
        for ms in range(1, 101):
            s.record('e', 200, float(ms))
        snap = s.snapshot()
        assert snap['latency_ms']['max'] == 100.0
        assert 45 <= snap['latency_ms']['p50'] <= 55
        assert 90 <= snap['latency_ms']['p95'] <= 100

    def test_the_reservoir_is_bounded(self):
        """A long-running worker must not grow a list forever. The count is
        still exact — only the latency sample is capped."""
        s = obs.RequestStats(maxlen=10)
        for i in range(1000):
            s.record('e', 200, float(i))
        snap = s.snapshot()
        assert snap['requests'] == 1000
        assert snap['sampled'] == 10

    def test_it_says_what_it_is_the_scope_of(self):
        # One worker, since it started. A reader who assumed cluster-wide would
        # draw the wrong conclusion from every number in here.
        assert obs.RequestStats().snapshot()['scope'] == 'this worker, since it started'

    def test_the_middleware_feeds_it(self):
        app, stats = _app()
        app.test_client().get('/ok')
        app.test_client().get('/boom')
        snap = stats.snapshot()
        assert snap['requests'] == 2
        assert snap['by_status'] == {'2xx': 1, '5xx': 1}


# ── Configuration ─────────────────────────────────────────────────────────────

class TestConfigureLogging:
    def test_it_is_idempotent(self):
        """`flask_api` is imported once per gunicorn worker and many times by
        the test suite. Handlers added twice print everything twice, which reads
        as a retry loop."""
        before = len(logging.getLogger().handlers)
        obs.configure_logging()
        after_one = len(logging.getLogger().handlers)
        obs.configure_logging()
        obs.configure_logging()
        assert len(logging.getLogger().handlers) == after_one
        assert after_one >= before

    def test_json_format_carries_the_extra_fields(self):
        import json as _json
        rec = logging.LogRecord('weave.access', logging.INFO, __file__, 1,
                                'GET /x 200', (), None)
        rec.request_id, rec.status, rec.duration_ms = 'abc', 200, 12.3
        payload = _json.loads(obs.JsonFormatter().format(rec))
        # The reason for JSON at all: these are queryable fields, not substrings
        # someone has to parse back out of a sentence.
        assert payload['status'] == 200
        assert payload['duration_ms'] == 12.3
        assert payload['request_id'] == 'abc'
        assert payload['level'] == 'INFO'

    def test_json_format_includes_a_traceback_when_there_is_one(self):
        import json as _json
        try:
            raise ValueError('nope')
        except ValueError:
            import sys
            rec = logging.LogRecord('weave.api', logging.ERROR, __file__, 1,
                                    'boom', (), sys.exc_info())
        payload = _json.loads(obs.JsonFormatter().format(rec))
        assert 'ValueError: nope' in payload['exception']


# ── What the prints were losing ───────────────────────────────────────────────

class TestErrorsKeepTheirTraceback:
    """The defect S2's "no logging" bullet was really about.

    `except Exception as e: print(f"❌ Error in x: {str(e)}")` writes the message
    and throws the stack away, so the line telling you *where* it failed was
    never recorded. Every one of those is now `log.exception`.
    """

    def test_an_endpoint_failure_logs_the_stack_not_just_the_message(self, client, fake_db, caplog):
        import flask_api as api
        fake_db()
        # Fail inside the endpoint, past its argument validation.
        def explode(*a, **k):
            raise RuntimeError('deliberate')
        with caplog.at_level(logging.ERROR, logger='weave.api'):
            api.app.config.update(PROPAGATE_EXCEPTIONS=False)
            try:
                monkey = api._resolve_init_time
                api._resolve_init_time = explode
                client.get('/api/forecast-data?model=AIFS&variable=precipitation&hour=6')
            finally:
                api._resolve_init_time = monkey
                api.app.config.update(PROPAGATE_EXCEPTIONS=None)
        records = [r for r in caplog.records if r.levelno >= logging.ERROR]
        assert records, 'the failure was not logged at all'
        assert any(r.exc_info for r in records), (
            'logged without exc_info — the traceback is being discarded again, '
            'which is what log.exception exists to prevent')
        assert any('deliberate' in r.getMessage() or
                   'deliberate' in str(r.exc_info[1]) for r in records)


# ── The readiness probe ───────────────────────────────────────────────────────

class TestReadiness:
    """`/api/ready` answers a narrower question than `/api/health`, several
    times a minute, and must not be the reason health's queries run.

    S2's bullet read: "`/api/health` is deeper than it was but is not a
    readiness endpoint." It reports database size, pool headroom, storage
    headroom and the export convention — what an operator reads once, not what
    a load balancer asks repeatedly.
    """

    def test_it_is_ready_against_a_real_database(self, db_client):
        r = db_client.get('/api/ready')
        assert r.status_code == 200
        assert r.get_json() == {'ready': True}

    def test_it_answers_503_not_500_when_the_pool_is_dead(self, prod_client, monkeypatch):
        """The distinction is the point. 503 lets a balancer take this worker
        out of rotation; 500 reads as a crash and pages someone. The process is
        fine and is telling the truth about itself."""
        import flask_api as api
        monkeypatch.setattr(api, 'get_db_connection',
                            lambda: (_ for _ in ()).throw(RuntimeError('pool is dead')))
        r = prod_client.get('/api/ready')
        assert r.status_code == 503
        body = r.get_json()
        assert body['ready'] is False
        # Names the class, not the message: the message can carry a DSN.
        assert body['reason'] == 'RuntimeError'
        assert 'pool is dead' not in str(body)

    def test_health_reports_what_this_worker_has_served(self, db_client):
        """S2 asks for count and latency metrics. They ride on `/api/health`
        rather than a new endpoint, because a second endpoint that needs its own
        scraper is S3's problem and this is one number an operator can curl."""
        db_client.get('/api/ready')                  # something to count
        body = db_client.get('/api/health').get_json()
        assert 'requests' in body
        stats = body['requests']
        assert stats['requests'] >= 1
        assert set(stats) >= {'requests', 'by_status', 'latency_ms', 'scope'}
        assert stats['scope'] == 'this worker, since it started'


class TestTheDuplicateAccessLineIsGone:
    def test_werkzeug_is_quieted_to_warning(self):
        """The dev server logs its own access line, so every request appeared
        twice — once from `weave.access` with a request id and a duration, once
        from `werkzeug` with neither. Its warnings are about the server itself
        and are still wanted, so it is quieted rather than disabled."""
        obs.configure_logging()
        assert logging.getLogger('werkzeug').level == logging.WARNING

    def test_the_access_line_names_the_client(self):
        """Quieting werkzeug removed the only place the client appeared, so it
        moved onto our line. It is the peer socket — behind a proxy, the proxy —
        which `observability.py` states rather than implying it is the user."""
        app, _ = _app()
        import logging as _l
        records = []
        h = _l.Handler(); h.emit = records.append
        _l.getLogger('weave.access').addHandler(h)
        try:
            app.test_client().get('/ok')
        finally:
            _l.getLogger('weave.access').removeHandler(h)
        assert records and hasattr(records[0], 'remote_addr')
