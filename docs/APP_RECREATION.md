# Adding a recreated app to Exodus

How an app recreated with REA (e.g. a macOS or Windows app rebuilt under a
generic name) becomes a built-in Exodus app. REA already covers *how* to study
and rebuild the original. This page only covers fitting the result into Exodus.

**Worked example:** the Calculator (`static/js/calculator/`, branch
`feat/calculator-app`, ported from the separate `JairoTheGyro/MacCalculator`
repo). When unsure, copy what it does.

## Workflow

1. Recreate and verify the app with REA in **its own repository**, not in
   Exodus. Reference screenshots of the original stay there.
2. In a fresh chat started in this repo, port it on a `feat/<app>-app` branch,
   then follow `AGENTS.md` (PR → merge → update the running app).
3. Move the app's line in `docs/EXODUS_ROADMAP.md` in the same PR.

## What the app must be

- **No-build browser code:** plain JavaScript ES modules and CSS in
  `static/js/<app>/`. No framework, no npm packages, no bundler.
- **Logic separate from screen:** `engine.js` holds behaviour with no DOM, so it
  can be tested in Node. `index.js` holds the window and UI.
- **A floating Exodus tool window:** use `makeWindowDraggable` from
  `static/js/windowDrag.js`. Export `open<App>`, `close<App>`, `is<App>Open`,
  `toggle<App>` (plus a default export of the same). No side effects on import.
- **Follows Exodus themes:** colours from `--bg`, `--fg`, `--panel`, `--border`,
  `--red` and the font from `--font-family`. Keep look-specific styling (rounding,
  shadows, title-bar style) in clearly marked CSS rules, so style packs (Apple-,
  Windows-, Material-like) can switch it later.
- **Works everywhere:** keyboard and screen-reader friendly, usable at phone
  width, and works in AI-Free mode (built-in apps don't need AI).
- **Internet only when truly needed:** fetch through a small same-origin server
  route (like `routes/calculator_routes.py`), say in the UI where the data comes
  from, and show an honest offline state.
- **Generic and original:** generic name, no trademarks, no copied code, icons,
  sounds or fonts from the original. Use open fonts and our own icons.

## Where to plug it in (today)

Until the planned app registry exists (Stage 3 in the roadmap), an app touches
these spots. Add your line next to the existing ones and keep everyone else's.

| File | What to add |
|---|---|
| `static/js/panels.js` | A lazy loader: `<app>: () => import('./<app>/index.js')` |
| `static/index.html` | The Tools-menu entry (`id="tool-<app>-btn"`, small SVG icon) |
| `static/app.js` | Click handler: `loadPanel('<app>')` → `toggle<App>()`, with a friendly toast on failure |
| `static/sw.js` | Precache the app's files and bump `CACHE_NAME` |
| `docker-compose.override.yml` | Read-only mounts for `static/js/<app>` and any new route file |
| `app.py` | Only if the app has a server route |

## Tests and checks

- `tests/test_<app>_js.py`: runs the engine's behaviour cases in Node through
  pytest. Cases come from observing the original app.
- A route test if there's a server route (see `tests/test_calculator_routes.py`).
- A practice check row in `docs/PRACTICE_TESTS.md`.
- A hand test in the running Exodus: open from the menu, every mode, two themes,
  phone width, AI-Free mode.
