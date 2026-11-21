# Testing Checklist

## 1. Console errors / CSP

- **Verified programmatically:** No inline scripts, no inline styles, no inline event handlers in the HTML. All JS in `script.js` and `motion.js`, all CSS in `style.css`. CSP header in HEADERS.md does not need `'unsafe-inline'`.
- **Must test in browser:** Open DevTools console, reload page. Confirm zero errors. Apply the CSP header (via a browser extension or Render) and confirm no violation reports.

## 2. No-JS / responsive / keyboard

- **No-JS:** Disable JavaScript. Intro loader hidden (`display:none` via `.has-js` guard). Status line shows "Status needs JavaScript". Copy buttons visible but non-functional (fallback: manual select). All content readable, all sections visible (no `opacity:0` without `.has-js`).
- **360px:** Hero title wraps cleanly. Pipeline cells stack to single column. Code boxes scroll horizontally. Bar chart fills width. Sample cards stack. Terminal mock scrolls. 20px gutters.
- **768px:** Pipeline cells 2–3 columns. Sample cards side by side. Comfortable reading width.
- **1280px:** Max-width 1240px container centers content. Pipeline cells 5 columns. Full rail pattern visible.
- **Keyboard:** Tab through — skip link appears on first Tab, all links, copy buttons, and nav reachable. Focus ring (2px cyan, 2px offset) visible on every interactive element. Sample cards show focus state.

## 3. Status line — three cases

- **Server awake:** Load page normally. Shows "Checking demo server…" (cyan pulsing dot), then "Demo server ready" (green dot with ring).
- **Server asleep:** Load when Render is cold. Shows "Waking the demo server (about 1 minute)…" (cyan pulsing dot), then ready or timeout.
- **Simulate closed port:** Change `API_URL` to `"https://localhost:9999"`. After 90s: "Demo server is asleep or unavailable" (muted dot).
- **Tab hidden:** Retries pause when tab hidden, resume on return.

## 4. Content accuracy

- **Privacy bullets:** Compare character-for-character against the five bullets in the brief. 5th bullet in warning box. Must be exact.
- **All links:** Click every external link — correct page, new tab, `rel="noopener noreferrer"`.
- **No third-party requests before video click:** Network tab shows only `/healthz` call. No YouTube, Google, or CDN requests.
- **ACCESS_CODE:** Appears as literal placeholder in terminal mock and code box. Never in JavaScript.

## 5. Motion — MOTION.md §7 verification

- **No console errors:** Reload with DevTools open. Zero errors from `motion.js`, `script.js`, or `style.css`. No WebGL warnings on fallback.
- **JS disabled:** Disable JS. All content visible. No intro loader. No canvas elements visible (they have no fallback content, which is correct — they are decorative).
- **Reduced motion:** Set `prefers-reduced-motion: reduce` in DevTools → Rendering. Intro loader hidden (`display:none`). No scroll reveals (all content at full opacity). No canvas animations. Bar chart fills at target width immediately. No transitions on any element.
- **Responsive canvases:** Hero cube canvas scales at 360px, 768px, 1280px. Wave canvas stays within section bounds. No horizontal overflow from either canvas.
- **Keyboard navigation with motion:** Tab order unaffected by reveals. Intro loader skippable via click, Escape, or any keydown. Skip button in intro is focusable.
- **Frame cost:** DevTools Performance tab → record 5 seconds of idle page with both canvases visible. Main thread frames under 8ms. If over, check DPR cap (should be ≤2).
- **Lighthouse:** Run on mobile and desktop. Accessibility ≥ 95, best-practices ≥ 95. Performance should be high given minimal page weight.
- **Hero stagger:** After intro exits (~1.6s), hero elements appear with staggered delays: eyebrow 0ms, title 0ms, sub 60ms, CTAs 120ms, status 120ms, terminal 180ms.
- **Terminal line stagger:** After terminal appears, lines stagger in with 50ms gaps (starting ~680ms after terminal's own reveal).
- **Pipeline cell stagger:** When pipeline enters viewport, cells stagger with 70ms gaps via CSS nth-child delays.
- **Eval bar animation:** When bar chart enters viewport, bars fill to target width over 700ms with 90ms stagger between bars.
- **Intro ceiling:** If page takes >5s to load, intro auto-exits. Clicking or pressing any key during intro skips it.

## 6. Page weight

- **Verified:** Total served files (HTML + CSS + JS × 2 + SVG favicon) should be well under 150KB combined. No images served initially. Run `Get-ChildItem site -Recurse | Where-Object { $_.Name -notmatch '\.md$' } | Measure-Object -Property Length -Sum` to confirm.
