# Shared spaces

A **space** is a named group of accounts, such as "Family" or "Work". Notes,
lists and calendars put in a space can be seen and edited by everyone in it.
Everything else stays private to its owner.

## Create a space and add people

Settings → Account → **Spaces**:

- **Create space:** type a name and press Create. You become its manager.
- **Add:** type someone's Exodus username. They must already have an account.
- **Make manager:** managers can rename the space, add and remove people, and
  delete it. A space always keeps at least one manager.
- **Leave:** anyone can leave a space.
- **Delete:** no notes are deleted. Each one goes back to the person who made it.

Workspace admins can manage every space. That does **not** let them read a
space's notes: only members can.

## Share a note or list

Open the note's **⋯** menu, then choose **Share to** → a space. Choose
**Only me** to make it private again. Shared notes show a small
"Family · by mom" tag.

| Who | Can |
|---|---|
| The note's owner | Everything: edit, delete, add pictures, move it in or out of a space |
| Space members | See it, edit its text and checklist, tick items, change colour and tags, pin, archive, set reminders |
| Everyone else | Nothing; they can't tell it exists |

When someone leaves or is removed, the notes they shared go back to being
private to them.

## Share a calendar

Calendar → **Settings** (gear) → next to a calendar, choose who can see it:
**Only me** or a space. Everyone in the space then sees its events and can add,
edit and delete them.

| Who | Can |
|---|---|
| The calendar's owner | Everything: rename, recolour, delete, export, change who can see it |
| Space members | See its events; add, edit and delete events |
| Everyone else | Nothing |

Calendars synced from another service (CalDAV, e.g. iCloud or Nextcloud) stay
personal for now, because they sync with their owner's own login.

## Good to know

- **Pictures** in a shared note can only be added by its owner. Pictures are
  stored per person, so members may not see them yet.
- **AI** never reads other people's notes: shared notes are not fed to a
  member's AI chats or memory.
- **Reminders** on a shared note notify its owner. Event reminders are
  personal: each person sets their own.
- Shared calendars appear in the Calendar. Home's agenda and the AI still show
  only your own calendars.
- **Coming next:** shared files.

## Files

- `src/spaces.py`: rules (membership, roles, limits).
- `routes/space_routes.py`: API at `/api/spaces`.
- `routes/note/note_routes.py`: notes that respect spaces.
- `routes/calendar_routes.py`: calendars that respect spaces.
- `static/js/calendar/spaces.js`: the Share to choice in Calendar Settings.
- `static/js/settings/spacesSettings.js`: the Settings card.
- `frontend/src/features/notes/ui/spaces.js`: the Notes badge and the Share to menu.
- `tests/test_shared_spaces.py`, `tests/test_shared_calendars.py`: isolation tests.
