# Shared spaces

A **space** is a named group of accounts, such as "Family" or "Work". Notes
and lists put in a space can be seen and edited by everyone in it. Everything
else stays private to its owner.

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

## Good to know

- **Pictures** in a shared note can only be added by its owner. Pictures are
  stored per person, so members may not see them yet.
- **AI** never reads other people's notes: shared notes are not fed to a
  member's AI chats or memory.
- **Reminders** on a shared note notify its owner.
- **Coming next:** shared calendars, then shared files.

## Files

- `src/spaces.py`: rules (membership, roles, limits).
- `routes/space_routes.py`: API at `/api/spaces`.
- `routes/note/note_routes.py`: notes that respect spaces.
- `static/js/settings/spacesSettings.js`: the Settings card.
- `frontend/src/features/notes/ui/spaces.js`: the Notes badge and the Share to menu.
- `tests/test_shared_spaces.py`: isolation tests.
