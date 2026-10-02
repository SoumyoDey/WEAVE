"""Structured logging, request IDs and request timing for the API.

Why this exists
---------------
`SYSTEM_DESIGN_PLAN.md` S2 asks for an observable service and records what was
there instead: **86 `print()` calls in `flask_api.py` and no `logging` import at
all.** That is not a style complaint. Three concrete consequences:

1. **Stack traces were being discarded.** Every endpoint ends
   `except Exception as e: print(f"❌ Error in x: {str(e)}")`, which prints the
   message and throws the traceback away. The one line a reader most needs —
   where it failed — was never written down. `log.exception` keeps it.
2. **Nothing correlated.** Two requests failing at once interleave their output
   with no way to tell which line belongs to which, and a user reporting "it
   broke" had nothing to quote.
3. **No timestamps and no levels**, so a log file could not be filtered, and
   "when did this start" had no answer.

What this module does NOT do
----------------------------
It does not replace the startup banner in `flask_api.py`'s `__main__` block —
45 of the 86 prints. That is a CLI courtesy printed by the dev server, not
service output, and `gunicorn` never runs it. Turning a banner into log records
would make it worse to read and no more useful to operate.

**That boundary hides a real gap, so it is stated rather than left implicit:**
the pool-headroom and storage-headroom warnings live in that same block, so in
production — where `__main__` does not run — *nobody is told*. Fixing that means
moving those checks to application start, which is a behaviour change to someone
else's work and belongs in its own commit.

Design notes
------------
**`X-Request-ID` is accepted from the caller but validated first.** Propagating
an inbound id is what makes a trace span a proxy and the app; writing an
unvalidated header into a log line is how a newline in that header forges a log
entry. Anything not short and alphanumeric is replaced rather than cleaned, so
there is no partial-sanitisation bug to find later.

**Timing is wall-clock around the Flask handler**, which is what a user feels.
It excludes time in the WSGI server and the network, so it is a floor on the
latency they see, not an estimate of it.

**Statistics are in-process and bounded.** One worker's view of its own traffic,
resetting on restart, with a fixed-size reservoir — `S3` is where a real metrics
backend belongs. The honest framing is "what this worker has seen since it
started", and `/api/health` reports it with that wording.
"""
import json
import logging
import os
import re
import threading
import time
import uuid
from collections import Counter, deque

from flask import g, has_request_context, request

# An id is either generated here or accepted from the caller, and an accepted
# one must be boring: a log line is a record, and a record that can contain a
# newline can contain a second record.
_SAFE_REQUEST_ID = re.compile(r'\A[A-Za-z0-9._-]{1,64}\Z')

REQUEST_ID_HEADER = 'X-Request-ID'

# Health and readiness are polled, often every few seconds. They are logged at
# DEBUG rather than dropped: silently unlogged traffic is how "the probe was
# failing all night" becomes unanswerable.
QUIET_PATHS = frozenset(
    p.strip() for p in
    os.environ.get('LOG_QUIET_PATHS', '/api/health,/api/ready').split(',')
    if p.strip()
)


def current_request_id():
    """The id of the request being served, or '-' outside one."""
    if not has_request_context():
        return '-'
    return getattr(g, 'request_id', '-')


class RequestIdFilter(logging.Filter):
    """Put the request id on every record, including ones from other libraries.

    A filter rather than an adapter so that `psycopg2`, `werkzeug` and anything
    else logging during a request is correlated too — those are exactly the
    records worth correlating, and they are emitted by code that knows nothing
    about this module.
    """

    def filter(self, record):
        record.request_id = current_request_id()
        return True


class TextFormatter(logging.Formatter):
    default_fmt = '%(asctime)s %(levelname)-8s [%(request_id)s] %(name)s: %(message)s'

    def __init__(self):
        super().__init__(self.default_fmt, datefmt='%Y-%m-%dT%H:%M:%S%z')


class JsonFormatter(logging.Formatter):
    """One JSON object per line, for a log shipper.

    `extra=` fields are carried through, which is what makes the access log
    queryable — `status`, `duration_ms` and `path` arrive as fields rather than
    as substrings someone has to parse back out of a sentence.
    """

    _STANDARD = frozenset(logging.LogRecord('', 0, '', 0, '', (), None).__dict__)

    def format(self, record):
        payload = {
            'ts':         self.formatTime(record, '%Y-%m-%dT%H:%M:%S%z'),
            'level':      record.levelname,
            'logger':     record.name,
            'request_id': getattr(record, 'request_id', '-'),
            'message':    record.getMessage(),
        }
        for key, value in record.__dict__.items():
            if key not in self._STANDARD and key not in payload:
                payload[key] = value
        if record.exc_info:
            payload['exception'] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


def configure_logging(level=None, fmt=None, stream=None):
    """Install handlers on the root logger. Idempotent.

    Idempotent because `flask_api` is imported by the test suite many times over
    and by gunicorn once per worker; handlers added twice print everything
    twice, which looks like a retry loop.
    """
    level = (level or os.environ.get('LOG_LEVEL', 'INFO')).upper()
    fmt = (fmt or os.environ.get('LOG_FORMAT', 'text')).lower()

    root = logging.getLogger()
    for existing in list(root.handlers):
        if getattr(existing, '_weave_observability', False):
            root.removeHandler(existing)

    handler = logging.StreamHandler(stream)       # stderr: stdout is for data
    handler.setFormatter(JsonFormatter() if fmt == 'json' else TextFormatter())
    handler.addFilter(RequestIdFilter())
    handler._weave_observability = True           # so a re-run replaces it
    root.addHandler(handler)
    root.setLevel(getattr(logging, level, logging.INFO))

    # Werkzeug's dev server logs its own access line, so every request appeared
    # twice — once from `weave.access` with a request id and a duration, once
    # from `werkzeug` with neither (it logs after the request context closes, so
    # its line reads `[-]`). Two lines per request is worse than one, and the
    # one worth keeping is ours. Quieted to WARNING rather than disabled: its
    # warnings are about the server itself and are worth hearing.
    #
    # This only affects the dev server. Under gunicorn werkzeug's logger is
    # unused, and gunicorn's own access log is configured separately.
    logging.getLogger('werkzeug').setLevel(logging.WARNING)
    return handler


class RequestStats:
    """Counts and latencies for this worker, since this worker started.

    Bounded on purpose: a reservoir of the most recent `maxlen` durations rather
    than every duration ever, so a long-running process does not grow without
    limit. Percentiles are therefore over recent traffic, which is the question
    being asked anyway — "is it slow now".
    """

    def __init__(self, maxlen=1000):
        self._lock = threading.Lock()
        self._durations = deque(maxlen=maxlen)
        self._by_status = Counter()
        self._by_endpoint = Counter()
        self._total = 0
        self._started = time.time()

    def record(self, endpoint, status, duration_ms):
        with self._lock:
            self._total += 1
            self._durations.append(duration_ms)
            self._by_status[f'{status // 100}xx'] += 1
            if endpoint:
                self._by_endpoint[endpoint] += 1

    def snapshot(self):
        with self._lock:
            durations = sorted(self._durations)
            by_status = dict(self._by_status)
            busiest = self._by_endpoint.most_common(5)
            total, started = self._total, self._started

        def pct(p):
            if not durations:
                return None
            # Nearest-rank, and clamped: for one sample every percentile is that
            # sample, which is correct and avoids an index error.
            i = min(int(round(p / 100 * len(durations) + 0.5)) - 1, len(durations) - 1)
            return round(durations[max(i, 0)], 1)

        return {
            'since':          round(time.time() - started, 1),
            'requests':       total,
            'by_status':      by_status,
            'latency_ms':     {'p50': pct(50), 'p95': pct(95),
                               'max': round(durations[-1], 1) if durations else None},
            'busiest':        [{'endpoint': e, 'requests': n} for e, n in busiest],
            'sampled':        len(durations),
            # Stated rather than left to be assumed: this is one worker's view
            # and it resets when the worker does.
            'scope':          'this worker, since it started',
        }


def install(app, stats=None, logger_name='weave.access'):
    """Give `app` request ids, an access log and timing. Returns the stats."""
    stats = stats if stats is not None else RequestStats()
    log = logging.getLogger(logger_name)

    @app.before_request
    def _start():                                  # pragma: no cover - trivial
        inbound = request.headers.get(REQUEST_ID_HEADER, '')
        g.request_id = inbound if _SAFE_REQUEST_ID.match(inbound) else uuid.uuid4().hex[:12]
        g.request_started = time.perf_counter()

    @app.after_request
    def _finish(response):
        started = getattr(g, 'request_started', None)
        duration_ms = (time.perf_counter() - started) * 1000 if started else 0.0
        endpoint = request.endpoint or request.path
        stats.record(endpoint, response.status_code, duration_ms)

        response.headers[REQUEST_ID_HEADER] = current_request_id()
        # A server error is worth a louder line than a 200, and a probe is worth
        # a quieter one. The level is the filter an operator actually uses.
        level = logging.ERROR if response.status_code >= 500 else (
            logging.DEBUG if request.path in QUIET_PATHS else logging.INFO)
        # `remote_addr` is carried because quieting werkzeug's duplicate line
        # removed the only place the client appeared. Note what it is: the peer
        # socket, so behind a reverse proxy it is the proxy. Reading
        # `X-Forwarded-For` instead would mean trusting a header, which needs
        # `ProxyFix` and a decision about which hops to trust — a deployment
        # change, not a logging one.
        log.log(level, '%s %s %s %.1fms from %s', request.method, request.path,
                response.status_code, duration_ms, request.remote_addr or '-',
                extra={'method': request.method, 'path': request.path,
                       'status': response.status_code,
                       'duration_ms': round(duration_ms, 1),
                       'endpoint': endpoint,
                       'remote_addr': request.remote_addr or '-'})
        return response

    return stats
