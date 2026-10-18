# Exodus roadmap

The living record of what we're doing to Exodus. **Every pull request moves its
line(s) in this file in the same PR**, so this page always matches reality.

- Plain-language lines, newest work at the top of each section.
- **Finished** entries keep their date and PR link.
- Stages run in order. A later stage can start early only if it can't make an
  earlier one harder (see "Why this order").

Status: **Needs to get started** · **Working on it** · **Finished**

---

## Working on it

- **Stage 1 · Updates:** bring in the three Dependabot update PRs (#6 GitHub
  Actions, #1 the bombadil test tool, #5 Python libraries). Keep MCP on version
  1, then rebuild the running app with a rollback image.

## Needs to get started

### Stage 1 · Stabilise and finish what's open
- Hand test and merge the **Calculator** (`feat/calculator-app`), then the
  **Clock** (`feat/clock-app`). They clash in `panels.js`, `sw.js` and the
  practice tests; keep both.
- **Sign-in under a sub-address** (`/exodus/`): test in a real browser with a
  temporary copy of Exodus and fake data. Pause the real Exodus while it runs.
- **License Tracker:** run every check for real, compare with GitHub, and record
  what works.

### Stage 2 · Catch up with the original Odysseus
- Merge the ~469 new upstream Odysseus changes on a sync branch. Keep every
  Exodus change, run all tests, rebuild, hand test, update the tracker's baseline.
- From then on, small regular catch-ups.

### Stage 3 · Foundations
- **App list and look settings:** adding an app touches one list plus its own
  folder. Shared look settings (rounding, title bar, buttons, font, spacing) that
  every app follows. Move Calculator and Clock onto them.
- **Services manager:** each service On / Off / Removed (data kept unless chosen)
  / Reinstall. Each person can hide apps and features they don't use.
- **Remove visible "Odysseus" text.** Keep the legally required credit and
  hidden internal names. Add a test that blocks new visible mentions.
- **Your own workspace name and logo** (admin setting, used everywhere).
- **Languages:** a translation system plus Spanish (Latin America) wave 1:
  sign-in, Home, Settings Essentials. Reviewed by Jairo in the browser.
- **Performance:** measure where memory and time go, then trim. Rust only for
  proven hot spots (no full rewrite).

### Stage 4 · Ready to share with family and friends
- **Shared spaces** (e.g. Family): shared notes, lists, calendars, files. Personal
  items stay private.
- **Phone app and private notifications:** one ntfy topic per person.
- **Welcome setup** for invited people: look, language, AI choice and spending
  cap, email and calendar.
- **AI per person:** cloud AI with a spend cap, a shared AI machine, or AI-Free.
- **Licence and secrets audit,** then make the repo public or add a
  "Source code" link (required by the AGPL when others use Exodus).
- **Home server** reachable privately (e.g. Tailscale), plus an "update the
  server" step. Hardware choice is Jairo's.
- Invite family and friends.

### Stage 5 · Looks, apps and convenience
- Style packs: **Apple-like → Windows-like → Material-like**, plus per-app
  overrides.
- **App launcher** (Dock / Start menu / app drawer, following the look).
- More apps (small utilities). Familiar layouts for Documents, Email, Calendar
  and Contacts. Spreadsheet and presentations later.
- Remaining Spanish waves.
- **"Move to Exodus"** wizard for Google, Apple/iCloud, Microsoft, Dropbox
  export files.
- **One-click updates:** the License Tracker checks daily, prepares tested
  update PRs and notifies; Jairo approves; Exodus updates itself.

### Stage 6 · Public
- A downloadable Exodus anyone can run (installer, setup guide, clean first run).
- Small teams (stronger isolation between accounts).
- Later: a hosted version with open signups.

### Parking lot
- **MCP 2 upgrade,** tested on its own branch. Then remove the Dependabot ignore
  rule.
- **Clearer rename error** when a username is reserved.

## Finished

- 2026-10-18 · This roadmap and the app recreation guide
  (`docs/APP_RECREATION.md`) created; full-permission workflow recorded in
  `AGENTS.md`.
- 2026-10-17 · Settings code loads once instead of twice
  ([#20](https://github.com/JairoTheGyro/Exodus/pull/20)).
- 2026-10-17 · Automatic Docker image publishing switched to manual-only
  ([#18](https://github.com/JairoTheGyro/Exodus/pull/18)).
- 2026-10-17 · Issue check can run on the private repo
  ([#16](https://github.com/JairoTheGyro/Exodus/pull/16)).
- 2026-10-17 · Full test suite passes. Fixed account-rename rollback, sign-in
  under a sub-address, duplicate settings code and outdated GPU setup files
  ([#14](https://github.com/JairoTheGyro/Exodus/pull/14)).
- 2026-10-17 · Workflow covers both the Mac copy and GitHub, and the running
  app is updated after merges
  ([#12](https://github.com/JairoTheGyro/Exodus/pull/12)).
- 2026-10-17 · Four always-failing GitHub checks fixed
  ([#10](https://github.com/JairoTheGyro/Exodus/pull/10)).
- 2026-10-17 · Branch → commit → pull request → merge workflow adopted
  ([#7](https://github.com/JairoTheGyro/Exodus/pull/7)).

---

## Why this order

1. Updates and open branches first, so we build on a clean, current base.
2. The Odysseus catch-up before big refactors (translations, text removal, app
   list), because those touch almost every screen and would make the catch-up
   much harder.
3. Privacy work (spaces, private alerts, licence audit) before anyone else uses
   Exodus.
4. Public release only after the licence and secrets audit.
