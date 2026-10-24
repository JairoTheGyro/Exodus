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

_Nothing in progress._

## Needs to get started

### Odysseus catch-up follow-ups (2026-10-19)
- **Small regular catch-ups** from now on: when the License Tracker shows new
  upstream changes, merge them on a `sync/odysseus-<date>` branch.
- **Check the "notify me" AI tool in a real chat.** Upstream now offers tools per
  turn by intent; Exodus added a notifications family so phrases like "ping me"
  or "ntfy" bring up `notify_user`, but a live chat should confirm it.
- **Next small catch-up:** the License Tracker already shows Odysseus `dev` moved
  past the new baseline (88772b32 → 268636c9 on 2026-10-19).

### Stage 3 · Foundations
- **Look picker in Settings:** a place in Settings → Appearance to choose the
  look for all apps or for one app (the switch itself exists; see Finished).
- **Services manager:** each service On / Off / Removed (data kept unless chosen)
  / Reinstall. Each person can hide apps and features they don't use.
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
- **Whole app under a sub-address:** only the sign-in page supports serving
  Exodus under a prefix like `/exodus/`. The rest of the app uses absolute paths
  (inherited from Odysseus). Not needed for the home-server plan, which gives
  Exodus its own address.
- **MCP 2 upgrade,** tested on its own branch. Then remove the Dependabot ignore
  rule.
- **Clearer rename error** when a username is reserved.

## Finished

- 2026-10-23 · **Visible "Odysseus" text removed:** screens, download file
  names, server messages and what the AI calls itself now say "Exodus".
  Deliberately kept: the legal credit, the mythological hero persona, hidden
  internal names, the wording Odysseus's own trained AI models need, and old
  markers that recognise data from before the rename.
  `tests/test_no_visible_odysseus.py` fails if a new visible mention appears.
- 2026-10-22 · **Pillow 13 security update:** GitHub's dependency check found
  35 security problems in the image library Pillow 12.3.0, fixed in 13.0.0. One
  AI-memory library (fastembed) still asks for an older Pillow, but only for
  image features Exodus doesn't use, so `requirements-overrides.txt` installs
  Pillow 13 on top. Applies to the app image at the next rebuild (Docker is
  off for now).
- 2026-10-22 · **Exodus is public:** Jairo kept his name on past commits and
  the repo went public. `main` is protected from force-pushes and deletion;
  secret scanning with push protection, Dependabot alerts and private
  vulnerability reporting are on. GitHub's checks are free again.
- 2026-10-22 · **Go-public audit:** no passwords, keys or private files
  anywhere in the published history, no personal details beyond Jairo's name on
  commits, credits and the AGPL "modified version" notice added, GitHub settings
  safe for a public repo. Details in `docs/GO_PUBLIC_AUDIT.md`.
- 2026-10-19 · **App list and look settings** (Stage 3): built-in apps now come
  from one list (`static/js/apps/registry.js`), which makes their Tools-menu
  entries and loading. Adding an app means one entry plus its own folder.
  Calculator and Clock moved onto it. Shared look settings (fonts, button shape,
  rounding, title-bar spacing) are read by both apps. A look can be chosen per
  app or for every app; "Apple-like" is the default and renders exactly as
  before, and an "Exodus" look proves the switch. License Tracker screen also
  checked on Jairo's own account: it shows the new versions.
- 2026-10-19 · **Service updates** (one PR, each service backed up first and its
  old image kept for rollback): Vaultwarden 1.37.3 → 1.37.4, ntfy 2.27.0 →
  2.32.0 (test message sent and received), DeepSeek Harness 0.1.7-rc.2 →
  0.2.1-rc.2 (it now refuses to listen on every address, so Exodus binds it to
  the container's own address; its new analytics stay off). ChromaDB was
  already 1.5.9: the tracker had recorded its bundled tool's version (1.4.4),
  which is the same source. Vaultwarden, ntfy and ChromaDB are now pinned to
  exact versions instead of `latest`, so a restart can never change them.
  SearXNG's newer image is still pinned by the catch-up and downloads the next
  time it's recreated.
- 2026-10-19 · **Hand test after the catch-up** (throwaway copy with a test
  admin, then the real app rebuilt): Home, Settings, License Tracker (live
  GitHub check, new baseline shown), Calendar, Tasks, Library, Workshop,
  Gallery, Memory, Email, Clock and Calculator (12 + 30 = 42) all open with no
  errors; Notes import, archive and unarchive work. Two bugs found and fixed:
  an open Notes panel now shows notes saved from Home right away
  ([#37](https://github.com/JairoTheGyro/Exodus/pull/37)), and Settings no longer
  causes a server error for accounts without email
  ([#39](https://github.com/JairoTheGyro/Exodus/pull/39)).
- 2026-10-19 · **Caught up with the original Odysseus**
  ([#35](https://github.com/JairoTheGyro/Exodus/pull/35); 470 upstream changes:
  split CSS, rebuilt Notes, new email safety layer, request authority, per-turn
  tool selection and more). Every Exodus change was kept: branding, invite-only
  teams, AI-Free mode, Vaultwarden, Workshop, Calculator, Clock, strict email
  encryption, the compact SearXNG search, Notes import/export and archive fixes,
  and the paper/copper/lavender/Temple themes. Exodus is pinned to its own
  Docker image so upstream's published image can't replace it.
- 2026-10-18 · **License Tracker checks verified:** all six projects checked
  live, and every result matched GitHub (Odysseus 469 changes ahead, Vaultwarden
  35, Harness 2,373, SearXNG 392, ChromaDB 324, ntfy 307, plus their newest
  releases). The one-minute wait, offline history and file-change details work.
  15 automated tracker tests pass.
- 2026-10-18 · **Sign-in under a sub-address tested** in a real browser (a
  temporary copy behind a proxy, fake data). The sign-in page works under
  `/exodus/`; the main app after sign-in doesn't (inherited, parked).
- 2026-10-18 · Dependabot kept proposing MCP 2; the ignore now covers every 2.x
  version, and fastapi 0.143.2 was taken
  ([#31](https://github.com/JairoTheGyro/Exodus/pull/31), replacing #25).
- 2026-10-18 · **Clock** app (macOS-style world clock, alarms, stopwatch,
  timers) merged alongside the Calculator (this PR).
- 2026-10-18 · **Calculator** app (basic, scientific, programmer, conversions,
  currency), hand-tested in the running Exodus
  ([#27](https://github.com/JairoTheGyro/Exodus/pull/27)).
- 2026-10-18 · **Updates:** GitHub Actions
  ([#6](https://github.com/JairoTheGyro/Exodus/pull/6)), the bombadil test tool
  ([#1](https://github.com/JairoTheGyro/Exodus/pull/1)) and the Python libraries
  with MCP held at version 1
  ([#24](https://github.com/JairoTheGyro/Exodus/pull/24), replacing #5). The app
  image was rebuilt; the previous image is kept as
  `sovereign-hub-odysseus:pre-deps-2026-10` for rollback.
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
4. Public release only after the licence and secrets audit (the audit and
   making the repo public were moved earlier on 2026-10-19 to get free checks).
