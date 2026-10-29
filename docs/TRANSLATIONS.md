# Translations

Exodus is written in English. Other languages translate the app's own wording;
anything not translated yet simply stays in English.

- **Choosing a language:** Settings → Appearance → Language (saved with your
  account), or the language menu at the bottom of the sign-in page (saved in
  that browser). A browser set to Spanish starts in Spanish.
- **Languages:** English, and Spanish for Latin America (`es-419`).
- **What's translated so far:** wave 1: the sign-in page, Home, and the
  everyday (Essentials) Settings; wave 2: the sidebar, menus (the chat "+"
  menu and the chat, folder, message, email and document menus) and toast
  notifications, including messages with names or numbers in them; wave 3:
  Notes, Calendar (including month and day names and dates), Email, the
  Library and the document editor, plus first-use tips and minimized-window
  chips; wave 4: the chat's controls (the top bar, the message box, message
  buttons and status lines, welcome tips), Memory, Skills, Themes, the
  Cookbook, Gallery and its image editor, Automations, Deep Research,
  Compare, and all of Settings, including Advanced. Later waves are listed in
  `docs/EXODUS_ROADMAP.md`. Chat titles and
  folder names in the sidebar are people's own words and are never
  translated, and neither are event titles, notes, emails, documents, chat
  messages, AI replies, memories, skills, photos, task names or research
  questions.
- **Left in English on purpose:** product and model names, command lines,
  the example prompts in Compare (they are sent to the AI as written) and
  the text Exodus sends to the AI behind the scenes.
- **Quick add in Calendar** still understands English phrases only ("lunch
  tomorrow 1pm"), so its examples stay in English.
- **AI replies:** chat answers come back in the chosen language
  (`src/reply_language.py` adds one instruction; nothing for English), unless
  the person asks for another language.

## How it works

`static/locales/es-419.json` maps the exact English text to Spanish:

```json
"messages": { "Sign In": "Iniciar sesión" },
"patterns": [["Good evening, {name}.", "Buenas noches, {name}."]]
```

`static/js/i18n.js` translates matching text where it appears in the
translated areas, including text that shows up later, and switches back
cleanly to English. People's own content (chats, documents, notes, email,
events), what people type into fields and anything marked `data-i18n-skip`
are never changed; a field's hint text (placeholder) is translated. The list
of elements that show people's content is `CONTENT` in `static/js/i18n.js`:
add to it when a new screen shows someone's own words as plain text. Code can
also call `t('English text', { name })`.

Write "Exodus" in translations even when a workspace has its own name; the
custom name is filled in automatically.

## Reviewing or fixing a translation

Open the screen in Spanish, find the wording, and edit its value in
`static/locales/es-419.json` (keep the English key exactly as it is). Use
Latin American Spanish ("computadora", "correo", "tú").

`tests/test_i18n.py` fails if a visible English string on the sign-in page, in
the Essentials Settings, the sidebar or the chat "+" menu has no Spanish entry,
if more than 5% of toast messages are untranslated, and if sample wording
from Notes, Calendar, Email, Documents, the chat, the tool windows or
Advanced Settings is missing, so new wording gets
translated in the same pull request.

Patterns are tried in order, so put a longer pattern (`"Daily at {time} ·
Next: {when}"`) before a shorter one that would also match it (`"Daily at
{time}"`).
