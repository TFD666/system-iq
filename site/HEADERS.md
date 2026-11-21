# Response Headers for Render Static Site

Set these in Render → Static Site → Headers (apply to all paths `/*`).

```
Content-Security-Policy: default-src 'none'; script-src 'self'; style-src 'self'; img-src 'self'; font-src 'none'; connect-src https://systemiq-api-pbwg.onrender.com; frame-src 'none'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'
```
Locks the page to its own scripts and styles; images only from self; fetch only to the API; no iframes, no fonts, no forms, no framing by other sites.

```
X-Content-Type-Options: nosniff
```
Prevents browsers from MIME-sniffing responses away from the declared content type.

```
Referrer-Policy: strict-origin-when-cross-origin
```
Sends the full URL to same-origin requests, only the origin to cross-origin HTTPS, nothing on downgrade to HTTP.

```
Permissions-Policy: camera=(), microphone=(), geolocation=(), interest-cohort=()
```
Disables device APIs and FLoC/Topics. The page uses none of them.

```
Cross-Origin-Opener-Policy: same-origin
```
Isolates the browsing context so cross-origin popups cannot access `window.opener`.

## Changes from the brief's draft CSP

- Removed `data:` from `img-src` — no data-URI images are used. Can be added back if needed later.
- Removed `https://i.ytimg.com` from `img-src` — demo section deleted, no YouTube thumbnails loaded.
- Removed `frame-src https://www.youtube-nocookie.com`, replaced with `frame-src 'none'` — no iframes on the page.

## Notes

- After the site is live, set `ALLOWED_ORIGIN` on the API to the site's exact address (https, no trailing slash).
- The page only ever calls `GET /healthz`, which is public and costs no quota.
- The page contains no secrets, no key/token/admin address. The access code on the page is a public, low-value placeholder.
- Two `<canvas>` elements (hero cube field, binary wave) are drawn by `motion.js`. Canvas rendering is same-origin and needs no CSP changes.
- The intro loader uses CSS keyframe animations and a JS controller in `motion.js`. Both are `'self'` resources — no `'unsafe-inline'` needed.
- `motion.js` is loaded with `defer` after `script.js`. Both are covered by `script-src 'self'`.
