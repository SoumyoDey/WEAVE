/**
 * One definition of where the API lives.
 *
 * This was copied into five files (`analysisApi`, `comparisonApi`,
 * `forecastApi`, `spatialApi`, `run`), each with the same
 * `process.env.REACT_APP_API_URL || 'http://localhost:5000/api'`. Five copies
 * of a constant is how one of them gets a different default — and the standing
 * lesson from the `init_time` migration is that replacing a resolver means
 * finding every copy of it.
 *
 * **The default is same-origin `/api` in a production build.** That is the
 * point of this module rather than just deduplication.
 * `REACT_APP_API_URL` is baked into the bundle at build time, so whatever it
 * holds ships to every browser in readable JavaScript. When it named a
 * separate origin, a password on the static site protected nothing: anyone who
 * opened the bundle could read the API's address and call it directly, with no
 * password in front of it. Same-origin means there is no second address to
 * find and no second thing to protect — the API is reachable only through the
 * same host, where the proxy's `basic_auth` already applies. See
 * `REVIEW_DEPLOY_PREREQS.md` §1 and the Caddyfile.
 *
 * Development still needs the absolute URL, because CRA serves the app on
 * :3000 while the API listens on :5000, so same-origin would resolve to the
 * dev server. `NODE_ENV` is set to `production` by `npm run build` and
 * `development` by `npm start`, so the two cases separate themselves without
 * any extra configuration.
 *
 * Setting `REACT_APP_API_URL` explicitly still wins, for the case where the API
 * genuinely is on another host. That is a deployment which cannot be protected
 * by a single password, and the note above is the reason why.
 */
/**
 * `127.0.0.1`, deliberately, and not `localhost`.
 *
 * `flask_api.py` runs the dev server with `host='0.0.0.0'`, which binds **IPv4
 * only** — `lsof -nP -iTCP:5000 -sTCP:LISTEN` shows one IPv4 socket and no
 * IPv6 one. On this machine `localhost` resolves to `::1` *first* and
 * `127.0.0.1` second, so every call to `http://localhost:5000` begins with a
 * connection to an address where nothing is listening. It is refused in about
 * 13 ms, and Chrome's Happy Eyeballs fallback to IPv4 then usually hides that.
 *
 * Usually. When the fallback does not happen — a burst of parallel requests on
 * a cold origin, before any address-family preference is cached — the refusal
 * reaches the page as `TypeError: Failed to fetch`, and **the server has no
 * record of it**, because the request never arrived (`NEXT_STEPS.md` §66).
 *
 * Naming the literal removes the ambiguity rather than relying on a fallback:
 * there is one address, it is the one the server binds, and it cannot resolve
 * to anything else. `REACT_APP_API_URL` still overrides for a real remote API.
 */
const DEV_FALLBACK = 'http://127.0.0.1:5000/api';

export const API_BASE =
  process.env.REACT_APP_API_URL ||
  (process.env.NODE_ENV === 'production' ? '/api' : DEV_FALLBACK);

export default API_BASE;
