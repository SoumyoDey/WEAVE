# Review deployment — fix before opening access

Two items left out of the cost estimate because they are not costs. Neither
changes the estimate.

> **Both are FIXED as of 2026-09-17.** This note is kept as the reasoning, not
> as a to-do list. What shipped:
>
> - **§1, auth.** `src/api/base.js` is now the single definition of the API base
>   and **defaults to same-origin `/api` in a production build**, so the bundle
>   ships no second origin to call around the password. Verified: a build with
>   `REACT_APP_API_URL` unset contains **zero** occurrences of a separate API
>   origin in the shipped JavaScript. `deploy/Caddyfile` serves both halves
>   behind one `basic_auth`, and `DEPLOY.md` §3 now binds gunicorn to
>   `127.0.0.1` so port 5000 is not a way past it.
> - **§2, the pool.** `DB_POOL_MAX` defaults to **8** instead of 20, which is
>   safe at every worker count the estimate assumes (8 × 8 = 64 < 100). The API
>   also checks the arithmetic against the live server at startup and reports it
>   at `/api/health` under `connection_pool`, so the condition is observable
>   rather than documented.
>
> **Two steps remain yours, and cannot be done for you:** generate the bcrypt
> hash with `caddy hash-password` and paste it into the Caddyfile, and point the
> hostname at the box. A password must not be written into a file by anything
> other than the person choosing it.
>
> One thing found while verifying: the default build also emits a 4.5 MB
> `main.*.js.map` carrying the complete source. `DEPLOY.md` §4 now builds with
> `GENERATE_SOURCEMAP=false`.

Same content as `Estimate Costs/WEAVE_Review_Deployment_Prerequisites.docx`; this copy
lives in the repo so it survives a clone. **That .docx is now out of date on
status** — its analysis still holds, but it does not know either item is fixed.

---

## 1. The API has no authentication, so the password must cover it

`Data/flask_api.py` defines 19 routes and none of them authenticate. The only
`token` references in the file are the input-validation regex (`_TOKEN_RE`) and the
data-version tag — there is no auth layer to enable.

The React build reaches the API cross-origin through `REACT_APP_API_URL`, which is
baked into the bundle at build time (`DEPLOY.md` §4). That URL therefore ships to
every browser in readable JavaScript. **A password on the static site alone protects
nothing** — anyone who opens the bundle can call `/api/*` directly.

**Fix — shipped in `deploy/Caddyfile`.** Serve the frontend and the API from one
origin behind a single Caddy vhost, and put the password on the whole vhost. The
file in the repo is the real thing, with comments; this is the shape of it:

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

Build the frontend with a same-origin API base so nothing points off-host. As of
2026-09-17 that is the **default** for a production build, so the variable is
better left unset than set — `src/api/base.js` resolves to `/api`:

```bash
npm ci
GENERATE_SOURCEMAP=false npm run build
```

Setting `REACT_APP_API_URL` to an absolute URL still works and is still correct
for a genuinely two-host deployment — which is also the deployment this section
says a single password cannot protect.

Caddy fetches and renews the TLS certificate itself, so the `DEPLOY.md` §7 item about
terminating TLS at the proxy is covered. Same-origin also makes the `CORS_ORIGIN`
step in `DEPLOY.md` §5 unnecessary — there is no cross-origin request left to allow.

---

## 2. Connection pool limits break at 5 or more concurrent users

`DEPLOY.md` §3 works the arithmetic for 4 workers: 4 × `DB_POOL_MAX` 20 = 80
connections, safely under PostgreSQL's default `max_connections` of 100.

Any deployment sized for more concurrency runs more workers, and the arithmetic
stops holding quickly:

| Workers | × DB_POOL_MAX 20 | vs. max_connections 100 |
|---|---|---|
| 2 | 40 | fine |
| 4 | 80 | fine |
| 6 | 120 | **over** |
| 8 | 160 | **over** |

Past the limit, workers fail to acquire a connection and requests error out under
exactly the load the extra workers were added to carry.

> **The worker counts above used to be tied to the AWS instance tiers in the cost
> estimate. That plan is off as of 2026-09-18 and the platform is undecided**, so
> they are stated here as plain worker counts instead. Nothing about the problem
> or the fix was platform-specific: the constraint is `workers × DB_POOL_MAX`
> against the server's own `max_connections`, which is true of any host. The
> check described below reads both from the live server rather than from a table,
> which is why re-anchoring this section needed no code change.

**Fix — shipped.** The per-worker pool now *defaults* to these values rather than
needing them set:

```
DB_POOL_MIN=2
DB_POOL_MAX=8
```

That gives 8 × 8 = 64 at eight workers, and clears every count in the table
above. Raising `max_connections`
in `postgresql.conf` above `workers × DB_POOL_MAX` is the other valid fix;
lowering the pool is the safer default, because each connection costs memory on
a box that is also running the database.

**And it is now checked rather than documented.** `_check_pool_headroom` in
`flask_api.py` reads the server's real `max_connections` — minus
`superuser_reserved_connections`, which are not available to this role, so the
usable ceiling is 97 rather than 100 — multiplies `DB_POOL_MAX` by the worker
count from `WEB_CONCURRENCY`, and reports both at startup and in `/api/health`
under `connection_pool`. It warns rather than refuses, because the worker count
is inferred from the environment and refusing would take a working deployment
down over an unset variable.

The reason this needs a check at all is that the failure is invisible until it
is not: everything works until enough users arrive together, and then requests
fail with a pool exhaustion that reads as a database fault.

---

*Sources: derived from `Data/flask_api.py` and `DEPLOY.md` in this repository as of
10 September 2026 — route count and absence of authentication read from the source,
worker and pool arithmetic from `DEPLOY.md` §3.*

*The worker counts originally came from the AWS instance tiers in
`Estimate Costs/WEAVE_Review_Deployment_Cost_Estimate.docx`. **Both .docx files
in `Estimate Costs/` are superseded as of 2026-09-18** — that estimate prices a
platform that is no longer the plan, and the prerequisites .docx does not know
either item is fixed. Their technical content still holds, because neither
prerequisite was ever AWS-specific; it is the platform and the status that are
stale. This file is the live version.*
