# Shared spaces

A **space** is a named group of accounts, such as "Family" or "Work". Notes,
lists, calendars and documents put in a space can be seen and edited by
everyone in it.
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

## Share a document

Library → **Documents** → a document's **⋯** menu → **Share to** → a space.
Choose **Only me** to make it private again. Shared documents show "Shared in
Family" (yours) or "Family · by mom" (someone else's).

| Who | Can |
|---|---|
| The document's owner | Everything: edit, archive, delete, export, change who can see it |
| Space members | Open it (including PDF and Word documents), edit its text, see and restore its versions, view and download the PDF |
| Everyone else | Nothing |

PDF and Word documents and pictures can be shared too. Members can **see**
the files behind a shared note or document and fill in a shared PDF form's
fields. Only the owner can add new files or pictures, add signatures, or let
the AI fill a form.

## Good to know

- **Pictures and files** in a shared note or document: members can see and
  download them. Only the owner can add new ones. A file is only visible
  through items shared in your spaces, and only if it belongs to that item's
  owner.
- **Signatures** stamped on a PDF show only for the person who signed.
- **Drawings** made in a note (stored in the owner's Gallery) don't show for
  members yet.
- **AI** never reads other people's notes: shared notes are not fed to a
  member's AI chats or memory. Shared calendars are the exception, read-only
  (see below).
- **Reminders** on a shared note notify its owner. Event reminders are
  personal: each person sets their own.
- Shared calendars appear in the Calendar, on Home's agenda and in the morning
  briefing. The **AI can read** them (and says who shares each one). It can't
  add, change or delete events in someone else's shared calendar: do that in
  the Calendar app. This keeps text another member typed into an event from
  steering the AI.
- Uploaded files in Library → Files are still personal.

## Files

- `src/spaces.py`: rules (membership, roles, limits).
- `routes/space_routes.py`: API at `/api/spaces`.
- `routes/note/note_routes.py`: notes that respect spaces.
- `routes/calendar_routes.py`: calendars that respect spaces.
- `static/js/calendar/spaces.js`: the Share to choice in Calendar Settings.
- `routes/document/document_routes.py` and `document_helpers.py`: documents
  that respect spaces.
- `routes/upload_routes.py` and `src/spaces.py` (`shared_upload_owner`):
  members reading files behind shared items.
- `static/js/documentLibrarySpaces.js`: the Library tag and Share to menu.
- `static/js/settings/spacesSettings.js`: the Settings card.
- `frontend/src/features/notes/ui/spaces.js`: the Notes badge and the Share to menu.
- `tests/test_shared_spaces.py`, `tests/test_shared_calendars.py`,
  `tests/test_shared_documents.py`, `tests/test_shared_uploads.py`: isolation
  tests.
