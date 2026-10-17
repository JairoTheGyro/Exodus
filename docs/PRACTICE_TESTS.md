# Exodus practice tests

Use these checks to answer “does this work for a person?” after a change. This is
a repeatable test plan, **not a record that every check has passed**. Record the
date, source revision, workspace mode, result and evidence when running it.

## How to run a safe check

- Prefer the existing disposable fixtures and synthetic accounts. A browser
  fixture needs a different hostname or browser profile from the real app:
  cookies are not separated by port. Never point broad tests at live user data.
- For a deliberate check in your own workspace, prefix every test item with
  `Practice —`, record its ID, and remove only those items afterward. Use dummy
  text/files/password entries. Do not export real notes just to test downloads.
- **Both** below means repeat in Full Exodus and AI-free using Settings →
  Workspace mode. AI-free is per account. A local server must still be running;
  “offline” means no external AI/internet dependency, not an absent backend.
- Live AI, web search, email and notifications require the corresponding working
  service. An agent may publish the synthetic test alert when authorized to run
  that test; sending mail to a real recipient needs an explicitly chosen test
  mailbox/recipient. Never use an unrelated person's address.
- Record **PASS**, **FAIL**, or **NOT RUN — reason**. A unit test with a mock
  provider cannot prove a real model, mail server, browser or phone works.
- Preserve the original mode, theme and settings and restore them after testing.
  Do not disable TLS verification, publish ports, install a model or boot the
  whole stack merely to make a check pass.

## Practice checks

Each row describes a human or browser-agent procedure and its pass condition.
Developer-only checks are explicitly identified. Service-dependent rows can be
run later without blocking ordinary local features.

| ID / mode | Do this | Pass condition |
| --- | --- | --- |
| P01 · Both · startup | Open the root Exodus address with no chat hash. Select a different theme, then reload; also inspect the signed-out login page. | Home opens without a New Chat flash. The first visible logo and browser-tab icon match the chosen palette; no original-color flash. Choosing Original deliberately restores the supplied colors. |
| P02 · Both · settings | Open Settings in Essentials, search for an advanced setting, and switch to Advanced. Choose Temple in Themes, then return to the starting theme. | Advanced settings remain reachable. Temple uses the retro layout and a reachable theme picker; switching back restores normal layout. No saved accounts or model configuration disappear. |
| P03 · Both · local services | Expand Local Services, open each description, and follow its shortcut. Change the opening preference once, then restore it. | Default links open a separate tab/context, preserving Exodus. SearXNG uses port 8080; ntfy uses 8091. Chroma's 8100 heartbeat returns JSON when running; its root is not presented as a dashboard. An offline service is reported as unavailable, not successful. |
| P04 · Both · licensing/updates | Open Settings → License Tracker. Inspect Odysseus, Vaultwarden and DeepSeek Harness; as admin, explicitly check upstream updates if internet access is intended. | Original names, licenses and repository links are visible. Recorded integrated revisions remain unchanged by checking for updates. Cached/latest-check dates and failures are honest. Merely opening the panel does not install updates. |
| P05 · Both · Notes search | Create `Practice — Groceries` with body `buy avocados`. Search `avocado`, then `AVOCADO`, then `no-such-practice-word`; clear the input. | Body-only matching finds the note in either case. No-match state is clear. Clearing restores all active notes/checklists immediately. The operation needs neither a model nor Chroma. |
| P06 · Both · categories and reminders | In a fresh test account, create three plain notes and one note with a reminder date **and time**. Leave delivery disabled for this filter test. Click All, Default and Reminders once from All. | All (4), Default (3), Reminders (1). Default hides the reminder; Reminders shows only the timed-reminder note. A date-only task deadline is not misclassified as a reminder. On an existing account compare count changes, not absolute totals. |
| P07 · Both · tags/archive | Add `Work` to one plain note and `Personal` to another. Check each tag chip. Archive the Work note, open Archive, then unarchive it. Reload. | Chips select matching notes, Default excludes custom-tagged notes, and counts follow saved records. Archived note leaves active All, appears in Archive, then returns after unarchive. Tags and state persist. Search text does not silently redefine total chip counts. |
| P08 · Both · checklists/Home tasks | Create `Practice — Packing` with `charger` and `notebook`. Complete one item in Home's Your tasks; reopen the checklist and toggle it back there. Try Due Today/Overdue/priority filters with deliberately set dates/priority. | Home and Notes show the same item state. Filters reflect actual saved fields, with no duplicate task store. Updates appear without a full-page reload. |
| P09 · Both · Notes export | With synthetic active and archived notes, tags and a partly completed checklist, use Notes → Export for Markdown ZIP and JSON. Open the downloads locally. | ZIP opens cleanly; Markdown has the original body, checked/unchecked items and metadata. JSON retains all note fields and archived records. Verify the archive option/default shown by the current UI; a default active-only ZIP must not be described as a complete backup. Timestamps and tags are preserved. Files contain plaintext, and attachment links do not imply attachment binaries were bundled. |
| P09I · Both · Notes JSON import | Export a synthetic tagged checklist and archived/private-memory note as JSON. In another test account choose Notes → Export / import → Import JSON backup, and select that file. Repeat once; try a malformed file. | Each import creates new IDs owned by the current account and never overwrites existing notes. Body, checklist state, tags, archive/privacy flags and timestamps survive. Archive view shows restored archived records. Invalid files save nothing; >10 MiB, >5,000 records or >20,000 checklist items across the file are refused. Counts/warnings explain omitted attachment/background files and chat/agent links. Existing open drafts stay intact. Older backups without an AI-memory flag remain excluded until deliberately enabled. Reminder dates follow current reminder settings. |
| P10 · Both · Library originals | In Library → Files upload a small `.txt` containing `Practice file: avocados`, then a PDF/image/CSV fixture. Download each. Cancel Delete once, then confirm deletion of the synthetic copies. | Filename, size and date are shown; download bytes match the input. Cancel keeps the file; confirm removes its uploaded copy and list entry, leaving the original file on the Mac alone. Files remain after a browser reload. Existing editable Documents still open separately. |
| P11 · Both · Library limits, developer | Run the Library integration suite with invalid extension, oversized file, duplicate name, traversal and symlink fixtures. | Oversized/unsupported uploads fail cleanly; files cannot escape the document directory or overwrite another upload. The current default size limit is 25 MiB unless configured otherwise. Failed uploads leave no registered partial file; a failed delete remains retryable. Do not create huge files in the real Library. |
| P12 · Both · Calendar quick add | Enter `Practice — Team catchup tomorrow at 2pm`; inspect the draft before saving. Try `Practice — Gym Friday 8am` and `Practice — Finish report next Monday`. Keep optional AI assist unchecked. | Correct title and next applicable local date are shown. Timed drafts default to one hour; date-only drafts are all-day. No model request is needed. Unsupported or ambiguous text asks for clarification rather than pretending to know. Saved events survive reload. |
| P13 · Both · Calendar/Home | Add an event for today using + New, change its title/time, then delete it. Separately add a one-day all-day event for today and repeat edit/delete. Keep Home available beneath the Calendar panel or in another same-account tab. | Today's schedule adds, changes and removes the correct event immediately after each successful save. A one-day all-day event is visible. A failed save does not announce success. Also cover agent-created events when exercising P22. |
| P14 · Both · scratchpad | Type `Practice — remember the blue notebook` into Home Quick capture. Wait for Saved, reload, then click Save to Notes once. Open the resulting note. | Text survives reload; one note with `quick-capture` tag is created and the saved pad clears. A repeated retry does not create duplicates or clear text typed afterward. Existing conflict/failure fixtures cover interrupted saves; do not induce failures against real data. |
| P15 · Both · reactive Home | Pin a practice note/document/upload, edit it, and archive/delete it as applicable. Change a synthetic goal, add/remove a personal shortcut, and change a checklist item. Watch Home without reloading. | Only affected widgets update; deleted/inactive items leave Recent & pinned/search. Pins point to the correct item. A refresh arriving while typing in a Home form does not erase the draft. Use a second same-account tab to exercise the event stream. |
| P16 · Both · diagnostics/focus/layout | Refresh System diagnostics. Start a focus timer, reload, stop it; reorder/collapse a widget and reload again. | RSS and data-disk free space are measurements, not invented savings. Notes/Calendar/mail cache statuses describe actual local probes; Vaultwarden offline is honest. A readable mail cache does not claim IMAP works. Timer and layout persist. Developer telemetry tests compare values to OS/database probes within tolerances. |
| P17 · Both · sharing/weather | With disposable accounts, check Home before opting into presence, then opt one account in and post a synthetic announcement. Inspect weather with its setting off. | No fake people, Slack/Teams messages or KPIs appear. Presence is voluntary/self-reported; only deliberately shared content appears to another account. Weather stays disabled without an external request. Enabling weather is a separate, explicit internet/provider choice, not offline functionality. |
| P18 · Both · mail | With the operator's authorized test mailbox, receive `Practice — Test subject`, refresh Home Inbox and click that row directly. Save/open a mail document and inspect Recent & pinned; also try an empty subject. Send a synthetic reply only to the agreed test recipient. | The correct account/folder/UID opens with message body. Recent & pinned uses the real subject or `(No Subject)`. Refresh polls without a page reload. Send/receive work without an LLM. A failed connection shows an error, not a success badge. |
| P19 · Both · mail TLS/templates | In account settings select IMAP 993 then 143, SMTP 465 then 587; restore the original settings without saving unintended changes. In a disposable mail fixture exercise an enabled templated away reply. | IMAP changes implicit TLS ↔ STARTTLS; SMTP changes SSL ↔ STARTTLS. Valid certificates succeed; self-signed/untrusted, expired and wrong-host certificates fail before credentials are sent. Template replies obey their opt-in window and duplicate controls without a model; AI-generated replies remain AI-only. Real delivery still needs P18. |
| P20 · Both · reminders/Automations | Use a synthetic timed note and a configured local notification destination. Test an ordinary reminder and a harmless non-AI maintenance automation, then an AI-dependent job in AI-free mode. | Ordinary reminder settings/delivery and non-AI integration save/test remain available to authorized users. Non-AI jobs can run; AI-dependent jobs pause/block. Record any over-broad block as a failure. The sidebar/window say Automations; Home Your tasks remains a human checklist. Do not create shell jobs touching real data. |
| P21 · Full · semantic note retrieval | With Chroma and a permitted embedding model available, save `Practice — Groceries` / `buy avocados`, wait for successful indexing, then ask `What do I need from the store?` without saying Groceries. | The answer is grounded in that owned note, not a lucky guess. Verify source/index evidence. Edit/delete the synthetic note and confirm stale content is not retrieved. In AI-free, saving/searching Notes remains local and automatic AI indexing/retrieval is blocked. Check the current per-note memory choice and archive policy before assuming either. |
| P22 · Full · unified AI pipeline | Subscribe to the configured local ntfy topic. Send: `Search the web for the latest status of open-source AI models, save a 2-bullet summary into my notes, and send an alert via ntfy when finished.` Approve only the requested actions if prompted. | Observe actual `web_search` execution using SearXNG, a new two-bullet note in Notes, and a real ntfy event. Record note ID, source URLs, event ID and indexing result without credentials. A model's “done” message alone is not proof. Distinguish approval pause, failed search, failed save, pending index and failed notification. Clean up only the test note. Repeat after changing provider; a prior provider's pass is not transferable. |
| P23 · Full · memory controls | Add a harmless explicit memory (`Practice favorite fruit is avocado`), find it in the existing Memory view, then delete it. Inspect indexed personal knowledge using its existing management controls. | Owner can see and remove saved items. Another test account cannot read them. Deletion removes the relevant saved record/index rather than only hiding a card. Personal memories and indexed documents/notes are related but different stores; deleting one is not a claim that every copy in chat history disappears. |
| P24 · Full · Code/shared model | As admin with Harness running, open Tools → Code. Select a model already connected in Exodus under Harness's Exodus provider. Ask it to create a dummy `practice-hello.txt` in its workspace and report the contents. | No second provider API key is required in Harness. Real file appears in the separate coding workspace. Removing/disabling that model in Exodus prevents further use rather than silently selecting another. Inspect approval behavior before permitting shell/network actions; Code is an admin coding workspace, not a guaranteed per-command approval sandbox. Non-admin and AI-free accounts cannot use its model gateway. |
| P25 · Full · Workshop | Describe a simple local counter with no personal information. Review scope first, build with Harness, then save/run it. Increment, reload and reopen from Library; try Export open app's entries and restore into the same synthetic app. | Assessment appears before generation. A changed brief requires review again. App source/versions use existing Documents; entries persist separately from Exodus code. Successful restore follows confirmation and respects revision checks. Basic builder remains available under Advanced. Real model output must function when used, not merely pass syntax checks. |
| P26 · Full · Workshop boundaries, developer | Exercise the existing assessment fixtures for green utility, yellow external/shared data and red payment/medical/password scopes; run restricted-Harness tool checks with the controlled provider. | Warnings/acknowledgments match assessed scope and cannot be bypassed by skipping the UI review. Headless Workshop sees only its submission tool; direct filesystem/shell tools are denied. Generated preview restrictions stay intact. Screening and syntax checks are not a security audit or proof an arbitrary generated app is safe. |
| P27 · Both · Vaultwarden | From Privacy Hub and Home open Vaultwarden at `https://127.0.0.1:8092/`. Check trusted HTTPS and server status. In a disposable vault, invite a synthetic member, register with the exact invited email, save a dummy login, lock and unlock it. | Same existing single vault service is used; SearXNG retains 8080. No TLS warning is bypassed. Uninvited signup stays closed. Vault login/master password is separate from Exodus. Health proves reachability, not phone sync. On the real vault the operator creates/enters their own master password; never disclose it in a test report. |
| P28 · Device-dependent · Vault/ntfy | Only after a separately approved reachable, trusted deployment exists, add a dummy vault item on one client and sync another; subscribe a phone to a synthetic ntfy alert. | Item changes reach the second authenticated client and a real alert arrives. Current loopback-only Mac URLs cannot serve a phone. Mark NOT RUN while Mac-only; do not open ports or weaken TLS as a testing workaround. Test away-from-home delivery separately from Wi-Fi. |
| P29 · Both · invitations/isolation | In the disposable team fixture create the first admin, invite two members in separate profiles, accept once, try replay/revocation/expiry, and change one member's mode/theme. Create distinct notes, files and calendar items for each. | First admin exists once; public registration stays closed; invitation creates an ordinary member and is single-use. Settings/content remain personal. Member cannot manage invitations or inherit an admin vault CLI session. Removing an Exodus member does not claim to remove their independent Vaultwarden account; follow both offboarding paths. |
| P30 · Both · backup/restore, developer | In disposable storage make a note, uploaded file, scratchpad, encrypted test-mail credential and dummy vault item. Run the documented backup/restore procedure into a separate target and verify each item. Inspect Git ignore rules/history scan findings separately. | Restored records match files and credentials remain decryptable because `.app_key` accompanies `app.db`. Vault restore is consistent and includes required files; Chroma persistent storage is covered separately. `.env`, databases, vault data, scratchpad and uploads stay out of Git. GitHub source backup is never presented as a runtime-data backup. Never restore over the running personal workspace merely to test recovery. |
| P31 · Both · account rename, developer | In the disposable team fixture, as admin rename a synthetic member `practice-a` to `practice-b`, then rename it back is refused (retired name). Separately, run `tests/test_rename_user_owner_sync.py`, which forces the owner migration to fail midway. | A successful rename moves the account, its sessions and owned records, and retires the old name. A failed rename returns the account to exactly its previous state: original name signed in, no new name created, and neither name left on the retired list. |
| P32 · Both · sub-path login and settings | Open the signed-out login page, then open Settings from Home, from the sidebar and from Workshop. With browser devtools → Network, check which `settings.js` URLs load. Developer: serve Exodus under a path prefix (for example `/exodus/`) and open its login page. | Login styling, Temple font and scripts load with no 404s, including under a path prefix. Exactly one `settings.js?v=…` URL loads, so every entry point opens the same Settings state. |

Cleanup: remove only recorded synthetic items, stop disposable fixtures, restore
original settings, and keep concise pass/fail evidence. Delete downloaded test
exports when no longer needed; they are not encrypted. Do not delete real service
volumes, existing data or upstream license/credit files.

## Existing automated coverage

These are existing tests, not a new test framework. They are **coverage pointers,
not today's results**. “Controlled” means mocks or a local fixture provider; it
does not mean the internet service or a paid model was used.

| Practice IDs | Automated files / coverage |
| --- | --- |
| P01–P02 | `tests/test_branding_compatibility.py`; `tests/helpers/test_logo_startup.mjs`; original identifiers/icon formats and logo load/race/error behavior. |
| P03–P04 | `tests/upstream_integration.py`; `tests/searxng_integration.py`; `tests/test_service_health_ntfy.py`; metadata/cache and controlled service requests. Browser link behavior still needs UI checking. |
| P05–P09I | `tests/notes_search_integration.py`; `tests/notes_organization_integration.py`; `tests/notes_export_integration.py`; `tests/notes_import_integration.py`; `tests/helpers/test_notes_import.mjs`; `tests/helpers/test_notes_archive_race.mjs`; `tests/test_notes_search_reset_on_reopen_js.py`; owner scoping, both modes, body search, archive/tags and request races, export fidelity/cleanup, import validation/rollback and Linux export RSS check. |
| P10–P11 | `tests/library_files_integration.py`; local bytes, file/metadata lifecycle, upload limits, path protections and both modes. |
| P12–P13 | `tests/calendar_quickadd_integration.py`; `tests/helpers/test_home_calendar_updates.mjs`; local dates/timezones/all-day events, optional AI failure, confirmed CRUD refresh. |
| P08, P14–P17 | `tests/home_integration.py`; `tests/home_dashboard_integration.py`; `tests/workspace_events_integration.py`; `tests/helpers/test_workspace_events.mjs`; `test_home_scratchpad.mjs`, `test_home_updates.mjs`, `test_home_form_preservation.mjs` in the same helpers directory. Data/state/event tests use disposable stores. |
| P18–P20 | `tests/helpers/test_home_email.mjs`; `tests/helpers/test_email_port_security.mjs`; `tests/test_email_tls_verification.py`; `tests/test_email_smtp_security.py`; `tests/test_email_template_independence.py`; `tests/test_email_legacy_config.py`; Home email tests also live in `tests/home_integration.py`. TLS tests use local certificate fixtures, not the real mailbox. Legacy credential tests cover default denial, owner-bound opt-in, redacted errors and encrypted seeding. |
| P20 · mode parity | `tests/mode_parity_integration.py`; `tests/helpers/test_automation_mode_ui.mjs`; ordinary maintenance/reminders remain available in AI-free, model jobs are blocked, owner context is retained, and Jobs labels/notification listeners work in both modes. Providers and delivery are controlled fixtures. |
| P21–P23 | `tests/test_exodus_native_notes.py`; `tests/notes_privacy_integration.py`; `tests/test_note_index_cleanup.py`; `tests/helpers/test_home_memory_policy.mjs`; `tests/chroma_integration.py`; `tests/ntfy_integration.py`; `tests/test_memory_owner_isolation.py`; `tests/test_memory_extractor_vector_cross_tenant.py`; `tests/test_embedding_lanes_memory.py`. Controlled privacy tests cover per-note/archive consent, stale-hit exclusion, owner-scoped deletion without embeddings, and consent-setting races. Chroma and ntfy suites include **live-service** checks: read prerequisites before running; offline unit passes do not substitute for them. |
| P24 | `tests/code_integration.py`; `tests/helpers/test_code_sync.mjs`; `tests/code_e2e_fixture.py` with `tests/helpers/run_code_harness_e2e.mjs`. The last pair requires actual Harness plus the explicitly controlled provider fixture. |
| P25–P26 | `tests/workshop_integration.py`; `tests/helpers/test_workshop_tools.mjs`; `tests/workshop_browser_fixture.py`; `tests/helpers/run_workshop_harness_e2e.mjs`. Restricted runtime E2E uses actual Harness with a controlled provider, not a real paid model. |
| P27–P29 | `tests/vaultwarden_integration.py`; `tests/test_prepare_vaultwarden.py`; `tests/team_accounts_integration.py`; `tests/helpers/test_vaultwarden_ui.mjs`; `tests/vaultwarden_e2e.py`; `tests/team_accounts_fixture.py`. Vault E2E temporarily creates its own project/ports/data and removes them; it does not create a personal vault account or prove phone sync. |
| P30 | `tests/test_local_backup_roundtrip.py`; `tests/test_local_backup_schedule.py`; synthetic SQLite/WAL snapshots and restore, files/keys, corruption/failure cleanup, permissions/retention, streaming memory, and the daily LaunchAgent configuration. Scheduling tests mock `launchctl`; they do not install a job. Existing preparation/CLI traversal tests cover their own scope. A complete restored-stack check remains separate; follow [the backup procedure](LOCAL_BACKUPS.md) and verify actual snapshot files before relying on a schedule. |
| P31 | `tests/test_rename_user_owner_sync.py` (forced owner-migration failure for admin and self rename, retired-name cleanup); `tests/team_accounts_integration.py`. |
| P32 | `tests/test_auth_root_path.py` (mount-aware login URLs and relative assets); `tests/test_external_context_tool_gate.py` (shared module version tokens). A real browser check under a path prefix remains manual. |

### Reusing the local isolated runner

With the repository's test dependencies and Node available, this command runs a
small useful offline subset in fresh temporary directories:

```sh
python3 scripts/cloud_test.py --suite notes-search --suite notes-organization --suite calendar --suite home-dashboard --suite workspace-events
```

Despite its historic name, this script runs **locally**. It does not create a
cloud task or install dependencies. Without `--suite` it runs its curated list,
not every test in the repository. Each suite starts a separate process with
isolated data/config and restricted Python network access. Avoid combining
standalone integration modules into one process: some configure paths at import.
On macOS the Linux `/proc` export RSS check is explicitly skipped; run that check
in the existing isolated Linux test environment to measure it. Browser rendering,
live provider requests, actual container launch and device sync remain separate.

For source-only UI helpers use the existing Node harnesses, for example
`node tests/helpers/test_logo_startup.mjs`. For disposable browser or service
fixtures read the header of that file first; do not infer a successful live check
from mocked fetch responses or an HTTP health status alone.

## Add a practice test with every feature

Before declaring a change finished, extend the appropriate row or add one with:

1. A realistic action using synthetic data, including prerequisites and mode.
2. The exact expected visible outcome and saved state after reopening/reload.
3. Failure/privacy boundaries relevant to the change (owner, offline, permissions).
4. Cleanup and the existing automated checks that support it.
5. What was actually run, what passed/failed, and what remains untested.

Non-AI functionality defaults to both modes. When an operation needs AI, test
its Full-mode behavior and the AI-free denial while preserving ordinary access.
Keep the evidence in the task's report/checklist; do not fill this reusable guide
with permanent green checks that become stale after later changes.
