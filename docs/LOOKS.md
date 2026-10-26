# Looks and the Dock

Exodus can look like the software you already know. There are two separate
choices, both in **Settings → Appearance**:

| Setting | What it changes |
|---|---|
| **Workspace look** | The whole of Exodus: fonts, window corners and shadows, window buttons, sidebar and menus, and which app launcher you get. |
| **App look** | Only the built-in apps (Calculator, Clock and the ones that come later). You can pick one look for every app, or a different look for a single app. |

Colours always come from your **theme** (Settings → Theme), so any theme works
with any look.

## Workspace looks

- **Exodus** (default): the classic Exodus style.
- **Apple-like**:
  - your computer's own system font instead of the monospace font (code
    stays monospace, and a font you picked on purpose in Themes, such as
    OpenDyslexic, is kept);
  - rounder windows with a soft shadow;
  - round red (close) and yellow (minimize) buttons at the top left of each
    window; hover over the title bar to see × and –;
  - a frosted sidebar and menus;
  - the **Dock** (below).

Windows-like (with a Start menu) and Google-like / Material (with an app
drawer) are next on the roadmap.

The Temple theme keeps its own retro style whatever look is chosen.

## The Dock

With the Apple-like look, a Dock at the bottom of the screen opens:

1. Home, New chat, Email, Calendar, Notes, Library and Automations;
2. every built-in app (Calculator, Clock, …);
3. Settings.

A dot under an icon means its window is open (or minimized). Clicking an icon
does exactly what the sidebar button does, so a second click minimizes, and a
minimized window comes back. Anything hidden in Settings → Appearance →
Sidebar, or by the AI-free workspace, is left out of the Dock too.

**Dock** setting (shown when Apple-like is picked):

| Choice | Behaviour |
|---|---|
| Show when the pointer reaches the bottom (default) | Hidden until you move the pointer to the bottom edge, or press Tab into it. Nothing is covered. |
| Always show | Always visible. The chat box and minimized-window chips move up so the Dock never covers them. |
| Hide | No Dock; use the sidebar. |

On phones and narrow windows (760 pixels wide or less) the Dock never shows,
because the sidebar is the better fit there.

## Good to know

- Both choices are saved **per browser**, like the App look, so a phone and a
  computer can look different. Other open tabs follow a change straight away.
- The look is applied before the page is drawn, so there's no flash of the
  Exodus look when the page loads.
- Looks are our own take on a familiar style. Exodus ships no Apple, Microsoft
  or Google fonts, icons or artwork.

## For developers

- `static/js/apps/workspaceLook.js`: the list of looks, which launcher each
  uses, and saving and applying the choice (`<html data-ui-look>`,
  `data-dock-mode`, `data-ui-font`).
- `static/css/91-look-apple.css`: every rule is scoped to
  `:root[data-ui-look="apple"]:not(.theme-temple)` (the Dock's own classes
  aside); `tests/test_workspace_look.py` checks this.
- `static/js/apps/dock.js`: the Dock. Entries come from the sidebar buttons
  and the app registry (`static/js/apps/registry.js`), so a new built-in app
  appears in the Dock without extra work.
- A new look adds an entry to `WORKSPACE_LOOKS` and `LAUNCHER_FOR_LOOK`, its
  own `9x-look-<name>.css`, and its launcher.
