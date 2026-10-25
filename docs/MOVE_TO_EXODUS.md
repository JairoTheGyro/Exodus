# Move to Exodus

Bring your calendars, contacts, Google Keep notes and files from Google,
Apple (iCloud) or Microsoft into Exodus. Everyone does this for themselves
in **Settings → Account → Move to Exodus**.

How it works:

1. Download an export from the service (steps below).
2. In Move to Exodus, choose the file and press **Look inside**. Exodus lists
   what it found. Nothing is imported yet.
3. Untick anything you don't want, then press **Import**. You get a list of
   what was added.

## Getting your export

### Google (Takeout)

1. Go to `takeout.google.com`.
2. Choose Calendar, Contacts, Keep and Drive (and anything else you want).
3. Pick a `.zip` export split into **2 GB** parts and download every part.
4. Upload one part at a time.

### Apple (iCloud)

- **Contacts:** on icloud.com open Contacts, select all, then Export vCard
  (`.vcf`).
- **Calendars:** in the Calendar app on a Mac, choose File → Export. Or share
  a calendar and download its `.ics` file.
- **Files:** download them from iCloud Drive as a `.zip`.

### Microsoft (Outlook and OneDrive)

- **Calendar:** in Outlook on the web, Settings → Calendar → Shared calendars
  → publish, then download the `.ics` link. Or export it from Outlook on a
  computer.
- **Contacts:** People → Manage contacts → Export contacts (`.csv`).
- **Files:** download from OneDrive as a `.zip`.

Dropbox and other file services work the same way: download a `.zip` and
upload it.

## What comes in

| In the export | Where it goes in Exodus |
|---|---|
| Calendars (`.ics`) | Your calendar with the same name (made if it doesn't exist yet). Events already there aren't added twice. |
| Contacts (`.vcf`, contacts `.csv`) | The address book. **Only the admin can import contacts**, because the address book is shared. Others see a message saying so. |
| Google Keep notes | Your notes. Checklists, pins, archive, colours and labels (as tags) come along. Trashed notes are left out. Imported notes aren't added to the AI's memory. |
| PDFs, text, CSV and pictures in Drive/iCloud/OneDrive | Your Library → Files. |

Left out for now, and the wizard says so:

- **Mail archives** (`.mbox`). Connect the email account in Settings → Email
  instead.
- **Photo libraries** (Google Photos, iCloud Photos).
- **Word, Excel and PowerPoint files.** Save them as PDF to bring them in.
- Pictures attached to Keep notes.

Importing the same export twice can add notes and files twice. Calendars are
safe to repeat.

## Limits and safety

- One upload can be up to 2 GB (set `EXODUS_MOVE_IN_MAX_BYTES` to change it).
  Single files over 25 MB inside the export are skipped.
- The upload is stored only for you, readable only by the server, and deleted
  after the import, when you press Cancel, or after 2 hours.
- Exodus never runs anything from the export. It skips unusual paths
  (like `../`), password-protected parts, and files that look like
  "zip bombs" (tiny files that expand enormously).
- Nothing is sent to the internet and no account sign-in is needed.

## Later

- Live "connect your Google/Microsoft account" transfers. These need an app
  registered with each provider.
- Photos into Gallery, Keep note pictures, mail archives.
