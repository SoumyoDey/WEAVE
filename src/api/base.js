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
const DEV_FALLBACK = 'http://localhost:5000/api';

export const API_BASE =
  process.env.REACT_APP_API_URL ||
  (process.env.NODE_ENV === 'production' ? '/api' : DEV_FALLBACK);

export default API_BASE;
