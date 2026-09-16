# Review deployment — fix before opening access

Two items left out of the cost estimate because they are not costs. Both still need
doing before external reviewers get the URL. Neither changes the estimate.

Same content as `Estimate Costs/WEAVE_Review_Deployment_Prerequisites.docx`; this copy
lives in the repo so it survives a clone.

---

## 1. The API has no authentication, so the password must cover it

`Data/flask_api.py` defines 19 routes and none of them authenticate. The only
`token` references in the file are the input-validation regex (`_TOKEN_RE`) and the
data-version tag — there is no auth layer to enable.

The React build reaches the API cross-origin through `REACT_APP_API_URL`, which is
baked into the bundle at build time (`DEPLOY.md` §4). That URL therefore ships to
every browser in readable JavaScript. **A password on the static site alone protects
nothing** — anyone who opens the bundle can call `/api/*` directly.

**Fix:** serve the frontend and the API from one origin behind a single Caddy vhost,
and put the password on the whole vhost.

```
weave-review.example.com {
    basic_auth {
        reviewer <bcrypt hash from: caddy hash-password>
    }
    handle /api/* {
        reverse_proxy localhost:5000
    }
    handle {
        root * /srv/weave/build
        try_files {path} /index.html
        file_server
    }
}
```

Build the frontend with a same-origin API base so nothing points off-host:

```bash
REACT_APP_API_URL="https://weave-review.example.com/api" npm ci
REACT_APP_API_URL="https://weave-review.example.com/api" npm run build
```

Caddy fetches and renews the TLS certificate itself, so the `DEPLOY.md` §7 item about
terminating TLS at the proxy is covered. Same-origin also makes the `CORS_ORIGIN`
step in `DEPLOY.md` §5 unnecessary — there is no cross-origin request left to allow.

---

## 2. Connection pool limits break at 5 or more concurrent users

`DEPLOY.md` §3 works the arithmetic for 4 workers: 4 × `DB_POOL_MAX` 20 = 80
connections, safely under PostgreSQL's default `max_connections` of 100.

The cost estimate sizes larger instances for higher concurrency, and the worker
counts go past that:

| Concurrent users | Workers | × DB_POOL_MAX 20 | vs. max_connections 100 |
|---|---|---|---|
| 1 | 2 | 40 | fine |
| 3 | 4 | 80 | fine |
| 5 | 6 | 120 | **over** |
| 10 | 8 | 160 | **over** |

Past the limit, workers fail to acquire a connection and requests error out under
exactly the load the bigger instance was bought to handle.

**Fix:** either lower the per-worker pool in `Data/.env` —

```
DB_POOL_MIN=2
DB_POOL_MAX=8
```

— giving 8 × 8 = 64 connections at the 10-user size, or raise `max_connections` in
`postgresql.conf` to comfortably exceed `workers × DB_POOL_MAX`. Lowering the pool is
the safer default; each connection costs memory on a box that is also running the
database.

---

*Sources: derived from `Data/flask_api.py` and `DEPLOY.md` in this repository as of
10 September 2026 — route count and absence of authentication read from the source,
worker and pool arithmetic from `DEPLOY.md` §3. Worker counts per tier are those in
the companion `Estimate Costs/WEAVE_Review_Deployment_Cost_Estimate.docx`.*
