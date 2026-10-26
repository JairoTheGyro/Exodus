# Exodus roadmap

The living record of what we're doing to Exodus. **Every pull request moves its
line(s) in this file in the same PR**, so this page always matches reality.

- Plain-language lines, newest work at the top of each section.
- **Finished** entries keep their date and PR link.
- Stages run in order. A later stage can start early only if it can't make an
  earlier one harder (see "Why this order").

Status: **Needs to get started** · **Working on it** · **Finished**

---

## Waiting on Jairo

Jairo gets a new computer with **36 GB of memory** in a few days (from
2026-10-24). Docker comes back then, and these three steps happen in order.
Claude reminds Jairo of them and walks through each one.

1. **Update and hand-test on the new computer.**
   - In the Exodus folder run `python3 scripts/update_local.py`. It backs up
     data, then rebuilds and restarts only what changed.
   - Try what was built while Docker was off:
     - **Services manager:** add `docker/service-manager.yml` to `COMPOSE_FILE`
       in `.env` first (`docs/SERVICES_MANAGER.md`).
     - **Spaces:** create a Family space and share a note, a calendar and a
       document (`docs/SHARED_SPACES.md`).
     - **Your AI:** set a tiny spending cap and check that AI pauses at it.
     - **Phone alerts:** subscribe in the ntfy app, then press Send test
       (`docs/PHONE_ALERTS.md`).
     - **Welcome setup:** invite a test account and walk through it.
     - **Odysseus catch-up:** run `docker compose pull searxng chromadb ntfy`
       for the new pinned images, and check search, memory, notifications and
       email export.
   - Click through the Spanish screens and note any wording that sounds off
     (Claude fixes it in `static/locales/es-419.json`).
   - Try **local AI** on the 36 GB computer with `docs/LOCAL_AI.md`: a model
     server (LM Studio or Ollama), model picks from the Cookbook, and
     connecting it as **Shared AI**. First run `python3 scripts/host_hardware.py`
     so Exodus sees the whole computer's memory.
   - **One-click updates:** run `python3 scripts/update_agent.py install`, then
     check Settings → License Tracker → Updates (`docs/UPDATES.md`).
2. **Pick the home server computer.** The new 36 GB computer could be it, or a
   separate always-on mini PC or Mac mini. Then follow `docs/HOME_SERVER.md`
   with Claude.
3. **Invite family and friends:** Settings → Team & invitations, and add them
   to Tailscale.

## Working on it

_Nothing in progress._

## Needs to get started

### Next up, in order (agreed 2026-10-25)
1. **More Spanish:** Notes, Calendar, Email and Documents, then menus and
   messages still in English.
2. **Smaller follow-ups:**
   - Move to Exodus: photos into Gallery, Keep note pictures, mail archives
     (`.mbox`), then live Google/Microsoft account connections.
   - Updates card: show new versions of SearXNG, Vaultwarden, ntfy and the
     other tracked projects.
   - Prepare tested catch-up PRs from the original Odysseus automatically.
3. **Waits for the new computer (Docker back on):** measure performance, then
   trim (Stage 3).

**Paused here (2026-10-25): looks.** Windows-like (with a Start menu) and
Google-like / Material (with an app drawer) are handed to separate agents, one
per look, so each one can be mastered on its own. Apple-like and its Dock are
done. See `docs/LOOKS.md` for how a new look plugs in.

### Odysseus catch-up follow-ups (2026-10-19)
- **Small regular catch-ups** from now on: when the License Tracker shows new
  upstream changes, merge them on a `sync/odysseus-<date>` branch.
- **Check the "notify me" AI tool in a real chat.** Upstream now offers tools per
  turn by intent; Exodus added a notifications family so phrases like "ping me"
  or "ntfy" bring up `notify_user`, but a live chat should confirm it.

### Stage 3 · Foundations
- **Performance:** measure where memory and time go, then trim. Rust only for
  proven hot spots (no full rewrite).

### Stage 4 · Ready to share with family and friends
- **Shared spaces, later:** drawings in shared notes; Library → Files uploads.
- Home server setup and inviting people: see **Waiting on Jairo**.

### Stage 5 · Looks, apps and convenience
- Style packs: **Windows-like → Material-like** (Apple-like is done).
- **App launcher** for those looks: Start menu (Windows-like), app drawer
  (Material-like). The Dock for Apple-like is done.
- More apps (small utilities). Familiar layouts for Documents, Email, Calendar
  and Contacts. Spreadsheet and presentations later.
- Remaining Spanish waves.
- "Move to Exodus" follow-ups: live Google/Microsoft account connections,
  photos into Gallery, Keep note pictures, mail archives (`.mbox`).
- Updates follow-ups: prepare tested catch-up PRs from the original Odysseus
  automatically, and show the other tracked projects' new versions (SearXNG,
  Vaultwarden, ntfy…) in the same Updates card.

### Stage 6 · Public
- Installer follow-ups: Windows support, and a prebuilt Exodus image so the
  first install doesn't need a 20–60 minute build.
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

- 2026-10-25 · **Apple-like look and the Dock:** Settings → Appearance →
  Workspace look switches the whole of Exodus to an Apple-like style: the
  computer's own system font, rounder windows with red and yellow buttons at
  the top left, a frosted sidebar and menus. A Dock at the bottom opens Home,
  chat, Email, Calendar, Notes, Library, Automations, every built-in app and
  Settings, with a dot under what's open. It can show always, only when the
  pointer reaches the bottom, or not at all. Colours still come from the theme,
  and phones keep the sidebar. See `docs/LOOKS.md`.
- 2026-10-25 · **One-command installer:** `curl … install.sh | bash` (or
  `./install.sh`) checks Docker, writes `.env` (invitation-only, local-only,
  a free port, the updater's project name), builds and starts Exodus,
  measures the computer, sets up one-click updates and shows the first admin's
  temporary password. Guide: `docs/INSTALL.md`. The home server guide now uses
  it, and by-hand installs keep `COMPOSE_PROJECT_NAME=sovereign-hub` (without
  it the updater wouldn't find a fresh install).
- 2026-10-25 · **One-click updates:** Exodus checks GitHub daily, and when a
  newer version has passed all its tests it notifies admins. Settings →
  License Tracker → Updates shows what's new; **Update now** has the update
  helper on the server (`scripts/update_agent.py`) back up, install exactly
  that version and restart, with rollback. Guide: `docs/UPDATES.md`.
- 2026-10-25 · **Local AI for any computer:** Settings → Account → Local AI
  (admins) shows the AI computer's real memory, what size of model fits and
  the best official models for it, or checks another computer you describe.
  In Docker, `scripts/host_hardware.py` measures the whole computer (the
  updater refreshes it), so the Cookbook no longer sees only Docker's share.
  `docs/LOCAL_AI.md` now has a guide by memory size.
- 2026-10-24 · **Move to Exodus:** in Settings → Account, anyone can upload a
  Google Takeout, iCloud or Microsoft export, see what's inside, and import
  calendars, Keep notes and files (contacts for the admin). Guide:
  `docs/MOVE_TO_EXODUS.md`.
- 2026-10-24 · **Members' own AI accounts:** in Your AI → My own cloud account,
  anyone can connect a private account at a well-known provider by pasting
  its key. Members can't type a web address, so their accounts can't reach the
  home network or Exodus's internal services.
- 2026-10-24 · **Local AI guide:** `docs/LOCAL_AI.md` covers what fits in
  36 GB, LM Studio or Ollama, picking models with the Cookbook (model picks
  checked against the live catalog), connecting them as Shared AI, and using
  a separate AI computer over Tailscale.
- 2026-10-24 · **Shared calendars for Home and the AI:** Home's agenda and the
  morning briefing include shared calendars. The AI can read them, labelled
  "shared by …", but only changes your own calendars.
- 2026-10-24 · **Shared PDFs, Word files and pictures:** space members can now
  open shared PDF and Word documents and see pictures in shared notes and
  documents. Files are read-only for members, and only files behind items
  shared with them, owned by that item's owner.
- 2026-10-24 · **Home server prep:** install guide (`docs/HOME_SERVER.md`:
  hardware choices, Docker, Tailscale with a private HTTPS address, first run,
  backups). The updater now backs up data first, keeps a `:rollback` image and
  the previous version, and `--rollback` goes back.
- 2026-10-24 · **Phone polish:** checked the main screens at iPhone size in a
  throwaway copy of Exodus (none spill sideways). Fixed the welcome being
  hidden behind Home's first-run screen. The sign-in page now installs as a
  home-screen app with the right name, and the icon is named after your
  workspace. Guide: `docs/PHONE_ALERTS.md`.
- 2026-10-24 · **AI per person:** Settings → Account → Your AI (also in the
  welcome) lets each person choose shared AI, their own cloud account or no
  AI. They can set a monthly spending cap, and admins can cap members. AI
  pauses for that person when the cap is reached.
- 2026-10-24 · **Welcome setup:** new accounts get a short guided first run.
  It covers language, full or AI-free workspace, app look, email and calendar,
  and phone alerts. Every step is skippable, and it can be rerun from
  Settings → Account. The AI provider and spending-cap choice will join it
  with "AI per person".
- 2026-10-24 · **Private phone alerts:** every account gets its own private
  ntfy topic; reminders and alerts go only there. Settings → Account → Phone
  alerts shows how to subscribe, sends a test and can make a new address.
  Guide: `docs/PHONE_ALERTS.md`.
- 2026-10-24 · **Shared documents:** share a text document from the Library's
  ⋯ menu with a space; members can open, edit and restore versions. PDF/Word
  documents stay personal for now.
- 2026-10-24 · **Shared calendars:** share a calendar you made in Exodus with
  a space from Calendar Settings; members see its events and can add, edit and
  delete them. Synced (CalDAV) calendars stay personal for now.
- 2026-10-24 · **Shared spaces (notes and lists):** create a space such as
  "Family" in Settings → Account → Spaces, add people, and share any note or
  checklist to it from its ⋯ menu. Only members can see it; everything else
  stays private. Guide: `docs/SHARED_SPACES.md`.
- 2026-10-24 · **Odysseus catch-up (33 changes):** security fixes for a
  compromised certificate authority (trusted-certificate updates, Chromium
  policy), safer model-endpoint addresses, email export to EML or PDF, better
  iPhone screen-edge layout, and a newer pinned SearXNG. All Exodus changes
  kept. New baseline `a0c93f38`.
- 2026-10-24 · **Services manager:** admins can turn each optional service on or
  off, remove it (data kept unless chosen) and reinstall it, from Settings →
  System → Services, through an opt-in, locked-down helper. Each person can
  hide apps they don't use (Clock, Calculator, Code and more), and that choice
  follows their account. Guide: `docs/SERVICES_MANAGER.md`.
- 2026-10-25 · **Spanish wave 2:** the sidebar, menus and toast notifications
  are in Spanish too (858 strings and 77 patterns in total). Chat titles and
  folder names stay as people wrote them.
- 2026-10-25 · **AI replies in your language:** when someone chooses Spanish,
  chat answers (normal and agent mode) come back in Latin American Spanish
  unless they ask for another language. English chats are unchanged.
- 2026-10-24 · **Translations and Spanish wave 1:** a translation system plus
  Latin American Spanish for the sign-in page, Home and the everyday Settings.
  Pick the language in Settings → Appearance or on the sign-in page; it's saved
  with your account. See `docs/TRANSLATIONS.md`.
- 2026-10-24 · **Your own workspace name and logo:** an admin sets them in
  Settings → System → Workspace name and logo. They replace "Exodus" in the
  sidebar, Home, welcome screen, Settings, browser tabs, tab icon, installed
  app and sign-in page. People's own content and the legal credit are never
  changed. Logos are cleaned and stored as PNG; back to the defaults any time.
- 2026-10-24 · **Look picker in Settings:** Settings → Appearance → App look
  chooses Apple-like or Exodus for all built-in apps, or a different look for a
  single app. New apps from the app list appear there automatically. Saved per
  browser for now.
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
