# Sovereign Solutions product principles

## Simple by default, customizable on demand

The first experience should use clear language, sensible defaults, and minimal
setup. Deeper configuration should be discoverable without overwhelming someone
who has never managed AI software. Preserve Odysseus as the shared interface and
foundation.

Reuse existing features and controls before adding new ones. Do not remove
features. A simpler view may tuck controls away only when users can still reach
them through a clear advanced path. Presentation choices must never silently
change permissions, privacy, provider selection, storage, or automation behavior.

AI can run through a local model or a provider connected with the user's own API
key. Setup must explain what is required, where requests go, and when costs may
apply. Do not claim that a model is installed, connected, or working until the
corresponding operation succeeds. Downloads and paid services are deliberate
user choices.

## Implemented first step

- Settings defaults to Essentials, with Advanced exposing every existing panel.
- The view is remembered in this browser and follows the existing logout and
  account-switch storage cleanup.
- Settings search still finds advanced panels for authorized users; selecting
  one reveals Advanced. Existing direct links do the same.
- Model setup introduces local and cloud choices using the existing forms,
  validation, and connection actions. Switching choices preserves entered values.
- The existing Docker-aware Ollama address helper is easier to find; it still
  only fills the form and does not install or connect a model.

This is the first interface improvement, not a completed zero-setup installer.
Custom agents, extensions, privacy controls, storage options, compute choices,
workflows, and developer tools remain part of the wider vision. Inspect and reuse
Odysseus's existing implementation before extending any of them. No placeholder
features or savings claims should stand in for working functionality.

## Local development

The active workflow, confirmed on 2026-10-01, is fully local: the user requests a
feature, we implement and verify it, and the user tests it. Changes may be
committed and pushed to GitHub at any time; the self-hosted copy and GitHub should
always be kept in sync in both directions. Cloud migration has been set aside;
the prepared cloud tooling remains optional and does not change where Exodus or
its Docker services run.

The Compose override reads edited source files directly from this checkout,
using the installed container image. UI changes need a browser refresh. Mounted
Python changes need an app restart; dependency changes need a deliberate rebuild.
Saved data and writable custom fonts keep their original mounts. The standard
Dockerfile continues to include the complete source for fresh builds.

## AI Workshop

- One guided brief for personal and lightweight business prototypes; green,
  yellow, and red scope screening. Screening is heuristic, not a safety audit.
- Generation defaults to headless Harness through the existing Exodus model
  gateway. The original direct provider builder remains under Advanced options. It is admin-only initially, to avoid bypassing non-admin model-spend
  limits. No model is installed or selected automatically. The user has chosen
  to leave model setup for later.
- Generated HTML goes into existing Documents and Library. The original editor,
  source export, and version controls remain available. Optional request IDs on
  document creation prevent duplicate tools when retrying a failed save.
- Marked Workshop HTML runs inside a separate, sandboxed nested preview. Its
  runtime blocks ordinary network requests and HTTP frame navigation and does
  not grant access to the account page. This is a prototype boundary, not a
  promise of total network isolation or protection from malicious code. Browser
  support varies; generated code can still be wrong or consume excessive CPU.
- Entries are separate from source and stored per document under the existing
  server data directory. Access uses the original document owner checks. Atomic
  writes, a 100 KB cap, and revision checks protect against common save failures
  and conflicting windows. This initial file store assumes one app worker.
- Entry backup/restore and downloadable review briefs work locally. No booking,
  public hosting, payments, account system, or external API integration is
  simulated. Source exports that use `window.workshop` need the Workshop host.
- Demo-only notices prohibit private information. Briefs sent to a cloud model
  leave the server and can incur provider charges. Saved entries are not sent
  by Workshop generation. This feature adds no telemetry or automatic updates;
  the wider Odysseus network behavior has not been audited here.

Validation: `tests/workshop_integration.py` runs isolated route/DB checks with a
mock provider; `tests/workshop_browser_fixture.py` supplies an explicitly labelled
disposable browser fixture for real save/reopen and preview restriction checks.
Neither needs a model or uses the user's database. Live AI output quality and
latency remain untested until a model is connected.

## Exodus identity and Temple theme

The visible product name is Exodus. The user's supplied sword-and-scales PNG is
preserved as the source for the welcome/login marks, sidebar and app icons.
The browser renders color variants without changing or duplicating that asset.
Match theme is the default; the Themes tab also offers Original and eight fixed
palettes. Login and Home reserve logo space until the selected palette is
decoded; never flash or fall back to the original colors unless Original is
selected. This preference stays in this browser across theme changes. The root
favicon shares the selected rendering; dedicated tool-route icons keep their
existing glyphs. Sidebar/welcome/login marks are modestly enlarged. Installed
PWA launcher icons remain the supplied static asset, as OS caches manage them.
Original icon paths contain correctly sized PNGs and a multi-size Windows ICO,
converted from the supplied asset. Internal provider identifiers and specialized
model instructions retain Odysseus; mythological references also stay Odysseus.
Reminder email recognition accepts both historical and current subject prefixes.
The setup template retains the upstream `.env.example` filename; only that exact
non-secret template is exempted from the `.env*` ignore rule. Odysseus remains the upstream foundation: preserve
its license and authorship. Existing storage keys, protocol headers, environment
variables, Docker service names, and internal identifiers retain their legacy
names to protect saved preferences and integrations. Do not mass-rename user data.

Temple is an optional preset in the existing theme picker. It uses a 640×480
logical workspace, integer enlargement where possible, and fit-to-screen scaling
on smaller displays. It uses the original public-domain TempleOS standard 8×8
glyph shapes, white/blue windows, square controls, and the 16-color VGA interface
palette. User images and other theme-preview swatches keep their own colors;
browser font smoothing can introduce intermediate pixel shades. Unsupported
Unicode characters fall back to monospace. Switching themes restores normal
layout; the persistent Themes control keeps the picker reachable.

Reference design: https://commons.wikimedia.org/wiki/File:TempleOS_4.05_session.png
Original constraints: https://templeos.info/Wb/Doc/Strategy.DD.HTML
Font provenance and rebuild instructions: `static/fonts/temple/README.md`.
This presentation does not change networking, account permissions, model routing,
or any security behavior to match the operating system.

## License Tracker

Settings includes License Tracker in both Essentials and Advanced for all users.
It credits Odysseus, Vaultwarden, DeepSeek Harness, SearXNG, ChromaDB and ntfy with their verified licenses,
repository, license links, and actual verification date. Extend the existing
panel and Settings registry when adding projects; preserve original notices.
This is a manually maintained list, not a complete dependency inventory or an
automatic license check. Opening it makes no external requests. Do not label a
license as current without checking upstream or replace the license shipped
with the version used merely because an upstream project changes its terms.

### Upstream update history

License Tracker also shows upstream revisions and public update history. Its
shipped manifest, `config/upstream_projects.json`, records each exact comparison
revision separately from the latest checked branch revision. Maintain
that baseline deliberately after an actual integration; checking for updates
must never change it. Partial backports do not advance the full baseline.
Container entries also record the inspected image digest and observation date;
these records are not enforced Compose pins or original installation dates.
Chroma's reference is the official CLI 1.4.4 release matching its executable;
the image lacks a source revision label, so full build provenance remains unverified.

Opening the panel only reads the local server cache. Admin-triggered checks,
older history, and file-detail requests may query the allowlisted public GitHub
repository. There is no scheduling, installation, code upload, or model usage.
Checks show releases and commit messages verbatim as text; file additions and
removals are not claims about features or compatibility. GitHub comparison
failure/divergence is shown explicitly. Failed checks retain the previous
snapshot and its original success date. Review reports include only public
upstream metadata and our recorded baseline, never application data or secrets.

History pages are anchored to the checked SHA to avoid shifting pagination.
The server retains up to 30 older pages and 40 commit-detail records per project;
new successful checks reset the older-page cache for the new snapshot. Full
release history and file lists beyond the first 100 files link to GitHub.
This records an upstream base plus Exodus modifications, not the exact version
of every dependency or proof that a change is already covered locally.

## Local Services

The collapsible Local Services sidebar group opens one description and its direct
browser shortcuts per service. It reuses the Tools section collapse behavior and
remembered state. The former Settings entry is moved here; older programmatic
Settings links still open the service overview. Links default to a new tab, with
an explicit same-tab option remembered in this browser and shared by the Local Services and Privacy Hub
services. The browser controls whether new contexts are tabs or windows.
Shortcuts target this
Docker setup: SearXNG at 127.0.0.1:8080, ChromaDB's API v2 heartbeat at
127.0.0.1:8100/api/v2/heartbeat, and ntfy at 127.0.0.1:8091. These are host-facing
browser links, not Docker service addresses. Update the shortcuts if published
ports change. Localhost refers to the browsing device; do not silently expose
services on the network to make remote-device links work.

ChromaDB's root returns 404 in the installed API server. Its heartbeat is a
connectivity check, not a dashboard or proof that all retrieval features work.
Descriptions link to the official documentation. Existing search, notification,
and service-diagnostic controls remain their source of configuration/status;
this panel adds no probes, subscriptions, installations, or extra containers.

## Privacy Hub

Privacy Hub and Home reuse the same Vaultwarden dialog in both modes. The
approved single-container deployment uses the official installed Vaultwarden
image with native HTTPS, loopback port 8092 and a dedicated bridge. Caddy is
removed. The public address is https://127.0.0.1:8092/ so native HSTS does not
upgrade unrelated localhost apps. SearXNG retains port 8080. Native response
protections stay enabled, and the vault opens on its own browser origin.

Vault data is persisted in ./data/vaultwarden:/data. Migration stops the vault,
backs up and verifies the old named volume, and retains that volume for rollback.
The admin secret is unchanged. Vault data, private TLS keys and admin credentials
are masked from both Exodus data aliases; Exodus receives only a public
certificate for strict health-check validation. Git never backs up runtime data.

Registration is invitation-only. Invite the first owner and subsequent members
through Vaultwarden administration; each sets their own master password. Native admin policy may override
these values. Ordinary vault signup does not grant admin-console access. The
operator completes certificate trust and enters their own master password; no
browser warnings or certificate validation are bypassed. The current web vault
requires HTTPS even on localhost, beyond Web Crypto's secure-context exception.

The normal bridge permits egress; icon fetching, push providers and unsolicited
update checks remain disabled. The former proxy cookie filter no longer exists;
localhost and 127.0.0.1 should be used as separate browser hosts for Exodus and
the vault. Health checks confirm only server/database reachability, not device
sync. Setup, backups, trust, onboarding and tests are in docs/VAULTWARDEN.md.

## Code / DeepSeek Harness

Tools → Code opens the shared companion dialog and launches Harness with its
own browser-session exchange. The current image installs the official npm
`@deepseek-ai/dsh@0.1.7-rc.2` package (npm latest when integrated), a developer
preview. The MIT license and release-source baseline are in License Tracker.
Newer prereleases are not installed automatically.

The `harness` service belongs to `sovereign-hub`, publishes only
127.0.0.1:8093, runs as the unprivileged Node user, and has no Docker socket,
Exodus source/database, or Vaultwarden volume mount. `data/code-projects` is
mounted at `/workspace`; `harness-home` persists sessions and settings. The
container can access the internet for intentional coding tasks. Upstream
telemetry is disabled through DSH_TELEMETRY_DISABLED. This is a demo environment,
not a production security boundary or an audited multi-user coding service.

On first opening Code, a signed-in administrator connects this single-operator
workspace to their own enabled/shared text-model catalog. Models explicitly
marked as lacking tool support are excluded. No real model is connected during
setup; the user previously chose to do that later. Model credentials stay in
Exodus. The container receives a scoped model-only token in a read-only mount;
that token authorizes only the two exact `/api/code/bridge/v1` routes. It cannot
access other Exodus APIs. Each generation rechecks administrator status,
endpoint ownership, enabled state, and hidden-model exclusions. Cloud providers
receive the coding prompts and file context, and may charge their API account.

The supervisor polls that local model list every five seconds and updates only
the managed `exodus` provider in Harness's Web profile, using upstream's profile
write lock and atomic writes. Other providers and plugin settings are preserved.
Users select the Exodus provider/model inside Harness. Existing sessions keep
their selected model; disabled/removed models fail rather than silently switching.
The gateway reuses Exodus's endpoint resolver and streaming provider adapters,
translating native tool calls and tool results to/from OpenAI Chat Completions.
This initial bridge exposes text input, with conservative 8K context/2K output
capacity defaults in Harness. It does not assert that every model supports tools,
vision, or every provider-specific reasoning control.

Harness's browser authentication and Host/Origin checks stay enabled. Its launch
token is captured in memory, suppressed from new startup log lines, and handed
to the signed-in administrator through Code's launcher. Port 3081 is an internal
control endpoint protected by the scoped bridge token; it is not published.
The CLI's webserver is configured to listen inside the container; Docker restricts
the host-facing port to loopback. Do not publish this preview on the network.

Tests: `tests/code_integration.py` checks access, live model catalog changes,
tool-call streaming, and error redaction using an isolated temporary database.
`tests/helpers/test_code_sync.mjs` verifies add/remove synchronization preserves
other provider settings. `tests/code_e2e_fixture.py` is an explicitly labelled
local fake provider used with the actual Harness runtime and actual Exodus
provider adapter; it never uses the live model database or a paid provider.
Live coding quality remains unverified until the user connects a real model.

## Workshop and Harness

Workshop is the guided, nontechnical entrance; Code remains the full direct
Harness interface. Workshop defaults to Harness and retains its original basic
one-response builder in Advanced options. The same enabled, owned/shared model
connections are reused. Models explicitly marked without tool support stay
available to the basic builder but cannot be selected for Harness builds.

A Workshop build starts one fresh headless profile inside the existing Harness
container. It does not inherit the Web profile, conversations, workspace files,
plugins, or provider credentials. Only the brief and, for revision requests, the
current app source are sent. Saved entries are excluded. The scoped model gateway
rechecks access on every request; cloud builds may make several billable requests.
No model is selected, downloaded, or purchased automatically.

The model sees only `submit_workshop_app`. Other coding tools are disabled or
hidden and independently denied by an execution guard. The runner requires the
Workshop restriction plugin before it can start. The submission tool checks a
complete HTML envelope, size, selected unsupported embeds/dependencies, and
inline JavaScript syntax using Node's parse-only `--check`. It never executes the
generated app. These checks are deliberately basic; they are not functional,
accessibility, malicious-code, or security audits. Rejected submissions return
feedback to the model for repair. A later rejected revision invalidates the
previous candidate. Completion requires an accepted source and a successful
Harness exit, followed by Exodus source normalization.

Only one Workshop build runs at a time. Runs are bounded to five minutes,
12 permitted submission calls, and 4 MB of process output. Cancellation or HTTP
client disconnection terminates the task; temporary profiles and source are
removed on completion/failure/cancellation. No prompts or reasoning are printed
to the supervisor log. The internal control API remains token-protected and
unpublished. No direct-shell or filesystem capability is added to Workshop.
These controls do not make the overall shared container an audited isolation
boundary against malicious administrators using the full Code interface.

Results use existing Documents/Library save, idempotent retry, export, preview,
entry storage, and ownership controls. No auto-deployment or background work
continues after the bounded build. The real model output still needs user testing.

Validation adds route tests for default engine, model compatibility, redacted
failures and the preserved basic builder; `tests/helpers/test_workshop_tools.mjs`
checks syntax-only behavior and restrictions. The isolated
`tests/helpers/run_workshop_harness_e2e.mjs` drives actual Harness through the real
Exodus gateway against the local fixture provider, checking rejection, repair,
acceptance, cancellation, cleanup, and the model-visible tool allowlist. No paid
model or live user database is used in these tests.

## Home and account-specific AI-free mode (2026-09-29)

The first visit offers Full Exodus or AI-free workspace. The choice belongs to
one account, including on installations used by several people. Settings →
Workspace mode changes it later. Existing chats, model connections, documents,
and other content are retained. This is an explicit product-mode choice, not a
role preset or a change in administrative permissions.

Home is available in both modes. Tasks reuse Notes checklists, including the
same completion state. Calendar uses existing owned calendars and recurring-event
expansion; meeting links come from actual event descriptions/locations. Files
come from the existing owned Document store; email reads the local unread cache.
Search uses ordinary text matching over owned notes/documents, cached email and
the existing permission-controlled contacts search. It never requests embeddings.
Home preferences, timers, manually maintained goals and personal shortcuts are
stored per account in `data/workspace-home.sqlite3`. Back up this file with the
rest of the data directory. A running timer survives a reload; stopping saves the
elapsed time, capped at the selected Pomodoro duration. Time tracked is not a
claim of time or money saved.

Team presence is opt-in. Status is self-reported, and recent presence reflects
explicit activity rather than an interval-based Home heartbeat. Announcements are explicitly posted
to signed-in users of this installation. Private work is not automatically
broadcast. There are no simulated teammates, messages, files, KPIs or activity.
Slack, Teams and document-comment providers are not integrated in this release.
Role presets reorder widgets only; they do not grant access or invent CRM data.
Widgets can be moved, hidden and collapsed, and load independently.

Weather is disabled by default. Enabling it sends the entered city to Open-Meteo
and uses a fixed conventional GFS forecast endpoint, with a 15-minute cache.
No device location is requested. The UI links the provider's terms and explains
that their free API is for noncommercial use. A business deployment must arrange
an appropriate weather service plan or leave this optional widget off.

AI-free mode removes the account's AI controls and blocks unreviewed/AI API
families server-side. Shared inference and embedding boundaries check account
context; async inference operations are tracked for cancellation. The scheduler
skips that account's automated jobs, email AI passes are suspended, and its Code
model gateway is blocked. Saved Workshop tools can still read/write their local
state without invoking a model. Other users and independently opened external
services are unaffected. This is not uninstalling shared software or stopping
all Docker services. A request already sent to an external provider cannot be
retracted; synchronous calls already in progress may finish. Full mode restores
access to the existing features.

Verification: `tests/home_integration.py` uses disposable databases for account
isolation, direct API denial, shared inference guards/cancellation, Notes task
reuse, stale edits, ownership/privileges, timer persistence, presence sharing,
layout validation, safe shortcuts, goals and weather opt-out. The disposable
`tests/home_browser_fixture.py` supports browser CRUD and persistence checks
without adding test data to the real workspace. Existing Workshop and Code
integration suites remain part of regression checks. A real connected model is
still intentionally deferred, following the user's earlier choice.

## Internal SearXNG grounding

The existing agent `web_search` tool uses one SearXNG JSON request when SearXNG
is the selected search provider. It returns at most five title/URL/snippet results
with existing citation metadata, without fetching full pages, opening tabs, or
silently switching providers. Request and agent-wait timeouts are five seconds;
unavailability and invalid responses return clear errors. Search results remain
untrusted external content. Existing web-tool permissions and AI-free restrictions
still apply. Other selected providers and Deep Research retain their existing paths.
The Local Services shortcut remains available for manual browsing.

`SEARXNG_BASE_URL` is the preferred environment variable; native execution defaults
to `http://localhost:8080`, and Compose defaults to `http://searxng:8080`.
A saved nonempty admin Search URL takes precedence. The legacy `SEARXNG_INSTANCE`
remains supported. `SEARXNG_CATEGORIES` defaults to `general`; individual tool calls
can override categories. General searches reuse `SEARXNG_GENERAL_ENGINES` (existing
default: bing,mojeek,presearch), because default engines can be CAPTCHA-blocked.
The SearXNG template and current active settings both enable html and json formats.
API reference: https://docs.searxng.org/dev/search_api.html

Standalone live check, without a model:
`docker exec sovereign-hub-odysseus-1 python scripts/test_searxng.py "Python programming" --count 3`
The script prints parsed JSON and exits nonzero on failure. An empty successful
search is reported honestly with count zero. Isolated request, parser, error,
native-argument and registered-agent tests live in `tests/searxng_integration.py`.

## Chroma HTTP knowledge and memory

Exodus reuses its existing Chroma HttpClient, embedding lanes, document indexing,
and pre-answer retrieval. `CHROMA_HOST` defaults to localhost natively and chromadb
in Compose; `CHROMA_PORT` defaults to 8000. The host-facing Docker port remains
8100. The old CHROMADB_HOST/CHROMADB_PORT variables remain native fallbacks.
`CHROMA_COLLECTION` defaults to `exodus_knowledge`, the local FastEmbed document
collection. Existing custom embedding and personal-memory collections remain
separate to avoid mixing incompatible vector dimensions. Existing old document
rows are copied only if missing, retaining ownership metadata and the old index.
No existing memories are deleted or reclassified as shared data.

The installed chromadb-client 1.5.9 transport defaults to unlimited timeouts.
`src/chroma_client.py` contains a narrow, version-tested compatibility shim that
sets the HTTP transport timeout before HttpClient makes its initialization
requests. TCP connection and HTTP operations use five seconds; this is not a
five-second limit for an entire multi-request indexing job. Client telemetry is
disabled. Retrieval failures leave chat context usable; startup failures can be
retried through the existing lazy RAG manager. Local embeddings use the existing
cached FastEmbed model; configured custom embedding endpoints keep their original
behavior. No chat model or paid provider was invoked for verification.

`POST /api/personal/text` accepts either `{ "text": "...", "title": "..." }`
or `{ "note_id": "..." }`, using the signed-in account and its document privilege.
Plain text reuses document upload, chunking, owner metadata, file storage and
deletion controls. Owned notes use the shared `src/note_indexing.py` service,
called by both this endpoint and a database post-commit hook. Creates and updates
queue background indexing of the latest title, content and checklist with the
note ID and owner; stable chunk IDs replace prior content without duplicates.
Deletes remove the indexed chunks. Rolled-back saves never enqueue indexing.
Retrieval rejects outdated or deleted note fingerprints even during an outage.
The hook calls the ingestion service directly instead of making a credentialed
HTTP request back into Exodus. AI-free accounts do not embed notes. Failed jobs
retry every 30 seconds in memory; a restart loses pending retries, so a note
saved during an outage may need another save or explicit reindex after restart.
The API reports incomplete indexing instead of claiming success. Existing file
uploads continue to work. These routes are blocked in AI-free mode.

Chat retrieves relevant knowledge automatically when document retrieval is enabled,
using the existing relevance threshold and context limits. Incognito skips knowledge
retrieval. Results are untrusted context, not new system instructions. No new
sidebar or duplicate memory UI is introduced.

The existing Chroma database was preserved while correcting the persistent volume
mount to `/data`, the running server's actual storage location. Back up that named
volume along with Exodus data. Do not delete volumes during upgrades.

Verification: `tests/chroma_integration.py` uses disposable documents, an isolated
SQL database and a temporary live Chroma collection. It checks real local semantic
retrieval, pre-answer context, account separation, note ingestion, AI-free denial,
incognito, offline chat continuation and a real silent HTTP server timeout.
Reference: https://docs.trychroma.com/production/chroma-server/client-server-mode

## Internal ntfy notification engine

`src/notifications.py` owns notification delivery. `dispatch_notification(message,
 title="Exodus", priority=3, tags=None, topic=None, owner=None, ai=False,
 incognito=False)` returns an honest sent/skipped/failed status. It sends a UTF-8
POST body with Title, Priority and optional Tags. Delivery has a three-second
HTTP timeout and overall async deadline, no retry, no redirect, and no cloud
fallback. `enqueue_notification(message, **kwargs)` is the nonblocking hook for
background task/search completion and system alerts: true means queued, not sent.
Its in-memory queue is bounded to 32 pending/running jobs and two workers; full
queues drop alerts rather than delaying work. Pending alerts do not survive app
restart. Callers must pass trusted owner, AI-origin and incognito context.

`NTFY_BASE_URL` defaults to http://ntfy:80 in Compose, or http://localhost:8091
for native use. `NTFY_DEFAULT_TOPIC` defaults to exodus-alerts. A saved enabled
ntfy integration overrides the environment URL and retains its bearer token.
An explicitly disabled saved integration prevents environment fallback.
`NTFY_ENABLED=false` disables all publication through this service. The server's
browser-facing URL is separately configured with `NTFY_PUBLIC_URL` (default
http://localhost:8091); its bind remains loopback-only.

Existing ntfy reminders now use the same service and preserve their selected
reminder topic. Browser/email/webhook choices are unchanged. No notification is
sent merely because the Local Services description opens, and the optional
manual browser link remains available. Service diagnostics recognize the
environment-configured ntfy server.

The `notify_user` agent tool publishes to the configured default topic; models
cannot choose a destination, topic, headers or credentials. It follows existing
administrator integration permissions, global tool-disable policy, delegated-token
restrictions, plan-mode restrictions, external-side-effect approval policy and
incognito denial. AI-origin calls recheck the owner's AI-free setting. Non-AI
system notifications can still operate in AI-free workspaces. No chat model was
connected for setup or tests, and search completions are not automatically spammed.

The default topic is an installation-wide notification destination, not a private
per-account inbox; keep agent alerts concise and free of private task content.
Firebase forwarding is disabled. `NTFY_CACHE_MESSAGES=true` preserves ntfy's normal
local replay behavior; false sends Cache:no for live subscribers only. Notification
bodies, credentials and server error bodies are not logged by this service.
Existing outbound private-network restrictions apply, metadata/link-local targets
are rejected, and validated addresses are pinned to prevent DNS rebinding.

Tests: `tests/ntfy_integration.py` verifies payloads, graceful failure, policy gates,
timeout, queue behavior, native agent dispatch and actual live subscription delivery
with a disposable, noncached test message. Existing reminder SSRF and ntfy health
regressions also pass. Reference: https://docs.ntfy.sh/publish/


## Hosted GPT-OSS native tools

Groq/OpenAI-compatible GPT-OSS uses the existing native function-call loop rather
than the textual fallback. Explicit endpoint tool-disable settings and Ollama
transport rules still apply. Active schemas are sent in `tools`; streamed
`tool_calls` are executed by the existing dispatcher and their call IDs/results
are returned to the model until completion. Notification intent now selects the
integration tools. Existing permissions, disabled tools and approval gates remain
in force: web results can require approval before note writes or notifications.

Verification includes `tests/test_exodus_native_notes.py` (controlled HTTP/SSE
provider, real model adapter and agent loop, actual note dispatcher, save hooks,
upserts/deletions, owner and AI-free checks), plus live Chroma background indexing
and ntfy integration tests. Controlled provider tests do not claim a live Groq
model completed the full workflow.


## Offline Notes organization

Notes keeps its existing local label/tag storage and archive flag. The API now
exposes `tags` as a string array backed by the same space-separated `label`, and
`is_archived` as an alias of `archived` (default false). Existing clients, notes,
agent tools and archive routes remain compatible. Tags use single words or
hyphenated phrases; empty tags are removed and duplicates normalized. Sending
`tags: []` clears tags. No separate category store is added: Work and Personal
are custom tags; Default means no reminder date/time and no visible custom tags.
Reminders includes notes with a reminder date/time, including overdue reminders
until cleared. A date-only task deadline is not a reminder.

All, Default, Reminders and custom-tag chips filter the current Notes view.
Counts use the full current active/archived list, independent of a text search.
Switching between active and archived views resets the chip selection. Archived
notes can be unarchived from their cards or open editor. These operations use
local SQLite and work in AI-Free mode. GET /api/notes supports literal,
case-insensitive title/content searching with q; the UI filters its loaded notes
and checklist text locally with a 250ms debounce and immediate clear.

Metadata edits trigger the existing database post-commit Chroma hook. Index
metadata includes tags and is_archived, and revision fingerprints reject stale
metadata until reindexing succeeds. AI-Free accounts still defer embedding; local
saves never depend on Chroma availability. Pending sync retains the previously
documented in-memory retry/restart limitation.

Automatic memory now also checks each note's ai_memory_enabled flag and the
account's ai_include_archived_notes preference (off by default). Explicitly
sharing a note with an agent and previously saved chat content are separate.
Revoked/deleted notes are rejected against live SQL on retrieval immediately;
owned vector cleanup uses model-free Chroma HTTP even in AI-free mode. Consent
and revision are rechecked around encoding. Failed cleanup retries are still
in-memory and can be lost across restart; durable deletion intents remain future
work before claiming guaranteed physical erasure while Chroma is unavailable.
Archive list requests reject stale responses and refresh after pending writes;
reminder badges never replace the archived list with active records.

Verification uses disposable AI-Free state in notes_search_integration.py and
notes_organization_integration.py, plus browser checks for tag editing, chip
counts/filter changes, archive/unarchive and persistence across reload.

## Local Notes export

Notes → Export / import offers active-only or active-plus-archived Markdown ZIP,
and JSON backup (active and archived notes). Exports ignore the current search/chip selection and preserve
existing account ownership rules; signed-in users cannot export other accounts.
The exact GET routes /api/notes/export/zip and /api/notes/export/json are available
in both workspace modes and do not invoke AI, Chroma, or external services.

ZIP files contain one UTF-8 Markdown file per note, collision-safe filenames,
JSON-quoted YAML frontmatter, original body text and readable Markdown checklists.
Frontmatter retains raw checklist JSON, timestamps, tags, IDs and other metadata.
Category is derived from existing organization: Reminders for a timed reminder,
otherwise the first custom tag or Default. All custom tags remain available.
JSON uses a versioned envelope with a notes array containing every stored Note
column and convenience tags/category/is_archived fields. Stored JSON columns
(items and ai_classification) remain their exact raw strings, including malformed
legacy values, for structural fidelity. Date strings retain stored precision;
no timezone is invented for database timestamps without one.

These exports include attachment references, not image binaries or other tables
such as chat sessions. Downloads are unencrypted, with an explicit UI notice.
Downloads use native browser
attachment handling without a whole-file JavaScript Blob. Generation uses a small
database batch and a temporary disk file, closed on failure, completion or client
disconnect. Memory scales with the largest note and ZIP entry directory, not the
combined note bodies. Disk space proportional to the resulting export is needed.

Verification: tests/notes_export_integration.py checks account isolation, AI-free
and full modes, raw column fidelity, Unicode/unsafe filenames, checklist nesting,
empty exports, cleanup and a 1,000-note / 62.5 MiB export. Measured peak additional
process RSS was 7.71 MiB (Python allocations 2.27 MiB) in the local Docker test;
these are test measurements, not universal memory limits. Browser downloads were
opened and checked using disposable notes in an AI-free fixture.

POST /api/notes/import/json restores a version-1 Exodus JSON backup as new,
caller-owned notes, never overwriting existing IDs. The whole bounded envelope
is validated before one transaction. Unsafe attachment references and foreign
chat/automation links are not restored; warnings explain omissions. Old backups
without memory consent default to automatic memory off. Existing save/event
hooks refresh Home and apply the current account's memory policy. Both modes
use the same local import path. Attachment files need the full local backup.

## Local daily backups

The Mac LaunchAgent installed by scripts/setup_local_backups.py invokes the
existing backup CLI at 03:00 local time and keeps the latest three automatic
archives. It has no resident process or additional container. Backups include
local data, uploaded files, app.db with .app_key, scratchpad metadata, Vaultwarden
and its TLS/admin files, and .env. SQLite uses consistent online snapshots;
archives are atomic and owner-only. Restore validates and stages before swapping
data, retaining a rollback directory that is ignored by Git and Docker builds.
These archives are not encrypted or off-device. Docker named volumes (including
Chroma/ntfy/Harness state) are not covered by this filesystem backup. The source
notes remain available to reindex, but do not claim complete vector/service-state
recovery. See docs/LOCAL_BACKUPS.md for coverage, restore and scheduling details.

## Original Library files

Library → Files stores original PDF, TXT, MD, CSV and image uploads without
parsing, conversion, OCR, embeddings or external calls. Existing Documents,
PDF editing, chat attachments and import-to-editor behavior remain available.
These are separate records because editable document versions and temporary
chat uploads have different lifecycles. Existing uploads are not copied or moved.

Compose maps the existing host data/documents directory to /data/documents in
the app container. EXODUS_DOCUMENTS_DIR overrides the location outside Compose;
the native default is DATA_DIR/documents. The new document_files table is in the
existing application database. Back up both that database and the documents
directory together. No new database service or vector collection is required.

GET /api/documents returns files, total, allowed extensions and max_upload_bytes,
with offset/limit pagination (50 by default, at most 200). POST
/api/documents/upload accepts one multipart file. GET /api/documents/{id}/download
streams the original bytes as an attachment. DELETE /api/documents/{id} removes
the file and registry entry. All four routes enforce identity, the existing
can_use_documents privilege, and owner filtering; AI-free mode permits them.

Names reuse the project's sanitizer and get a random ID prefix so equal names
never overwrite each other. Registry paths are independently validated; symlink
files cannot be followed. Supported extensions determine the MIME label; this
is storage, not a file-format or malware scanner. Downloads are attachments with
nosniff/sandbox headers, so uploaded SVGs or disguised content are not previewed
as active application pages. The upload limit defaults to 25 MiB via
EXODUS_DOCUMENT_UPLOAD_MAX_BYTES. Multipart request size is capped before/during
parsing (file limit plus 64 KiB envelope), and storage copies in 64 KiB chunks.
Failed saves clean up partial files. Downloads close their handles on disconnect.

Deletion records durable intent before removing bytes. If disk/DB removal fails,
the pending entry remains visible with Retry delete; downloads are blocked until
removal completes. User deletion requires a clear permanent-delete confirmation.
A successful deletion is not reversible. A process crash during an unfinished
upload can leave an unlisted partial file; no automatic destructive cleanup of
this directory is introduced. The host file is not touched by deleting the
uploaded copy.

Verification: tests/library_files_integration.py uses isolated SQLite/disk and
checks supported extensions, both workspace modes, exact bytes, metadata,
account/privilege boundaries, path sanitizing, symlink refusal, size limits,
chunked requests, failed-save cleanup, retryable deletion and original Documents
behavior. Browser verification uses an isolated AI-free workspace and compares
a file uploaded and downloaded through the actual controls byte for byte.


## Offline Calendar Quick add and Home refresh

Quick add uses a bounded English parser in `src/calendar_quick_add.py` by
default in both workspace modes. It recognizes today/tomorrow, weekdays,
ISO and named-month dates, 12/24-hour times, noon/midnight, time ranges, relative
minutes/hours/days/weeks, and explicit durations. No new dependency, model,
embedding, or external API is needed; the local Exodus server must be running.
Ambiguous numeric dates and unsupported recurrence instructions ask for a clearer
input. Date-free drafts use today with a notice. The existing form remains the
confirmation step before saving; date-only events are all-day and timed events
without an end default to one hour. “Next Monday” means the next occurrence,
strictly a week later when today is already Monday.

Full mode retains explicit, unchecked-by-default AI assist. Only choosing it
sends the description to the existing configured utility/default provider.
Inference is capped at five seconds, validated, and falls back to the local draft
on errors or missing configuration. AI-Free hides the option and independently
blocks inference even if the client requests it. There is no provider-specific
or Groq prerequisite. The POST quick-parse route is now allowed in AI-Free.

Confirmed calendar creates, edits and deletes notify Home to reload only its
schedule. Home also listens to the existing agent calendar-refresh signal; a
failed save does not announce success. Stale overlapping schedule responses are
ignored. All-day forms use inclusive displayed dates and exclusive stored ends;
nonpositive stored durations are normalized on create/update. Timed form saves
use the selected date's offset rather than today's offset, preserving DST.
Home sends local_start/local_end dates for floating all-day events, separately
from UTC bounds for timed events. Recurrence uses the same date window, preventing
tomorrow's or yesterday's all-day events from leaking into Today across timezones.

Verification: `tests/calendar_quickadd_integration.py` uses isolated SQLite and
blocked/mock inference for parsing, both modes, persistence, timezone anchoring,
optional-provider fallback and all-day visibility. Existing calendar/Home tests
remain in use. `tests/helpers/test_home_calendar_updates.mjs` checks confirmed
save notifications, failed-save rollback and the agent completion signal.
The disposable Home browser fixture verifies Quick add and immediate Home updates
without changing real calendar data.


## Verified mail connections and template replies

Email IMAP and SMTP connections, including the account Test action, require
certificate-chain and hostname verification using the system trust store.
STARTTLS failures stop before authentication; no plaintext or unverified retry
is allowed. STARTTLS off means implicit TLS even on custom IMAP ports. SMTP None
is blocked. Local mail servers and bridges must provide trusted certificates;
this change does not alter the system trust store or saved credentials.
Both account forms pair IMAP 993 with implicit TLS and 143 with STARTTLS, and
SMTP 465 with SSL/TLS and 587 with STARTTLS. Custom ports retain TLS controls.

Opted-in templated away replies run separately before optional AI processing,
including in AI-Free mode or without a model. Existing account scopes, date
windows, automated-sender exclusion and duplicate/cooldown checks remain in use.
The existing incoming-mail event trigger is retained; this adds no new polling
service and does not enable replies automatically. AI summaries, draft generation,
classification and calendar extraction remain blocked in AI-Free mode.

Verification includes disposable loopback IMAP/SMTP servers: trusted certificates
connect; untrusted self-signed, expired and wrong-host certificates fail before
credentials are sent, for both implicit TLS and STARTTLS. Template tests use
mock mail delivery and an isolated duplicate-reply database. Both settings forms
have port-event checks in tests/helpers/test_email_port_security.mjs.

## Home email access

In both workspace modes, Home Inbox rows open the existing Email reader directly
with the row's account, folder and UID. Direct opens do not depend on the message
appearing on the first inbox page. An unavailable explicit account never falls
back to another account. Returning from the reader loads the normal inbox list.
Home's normal load reads the local unread cache; its Inbox refresh button makes
an explicit mail-server request through the existing list route and cache-buster.
Failures show an honest status, and older responses cannot replace newer results.

Recent & pinned keeps the existing owned Document store and pins. For email
documents it displays the saved envelope Subject, or `(No Subject)` when blank,
rather than the generic draft title. Quoted-body subjects are not used. No new
email history database or AI processing is introduced. Verification includes
Home backend tests in both modes, controlled browser-loader regression tests,
and a live Home Test-message reader/open and manual Inbox refresh check.

## Reactive Home, scratchpad and local diagnostics

Home uses one authenticated, owner-scoped event stream and a shared client event
bus. Successful Notes, Calendar, Library, mail-cache and Home preference writes
invalidate the relevant widgets after commit. Failed or rolled-back writes do
not announce success. Reconnecting or returning to the page refreshes current
state through the existing permission-checked APIs. Events contain only topic
names, not private content or account identities. The initial implementation
assumes one application worker, matching this Docker setup; it is not a durable
or multi-server event broker. The automation event bus remains separate.

Quick capture is one autosaving scratchpad with a 500 ms debounce. The primary
account's plain Markdown lives at `/data/scratchpad.md` in Docker, with private
per-account directories for additional accounts. `/data` aliases the existing
host data directory rather than copying it. Native installations use DATA_DIR,
or EXODUS_SCRATCHPAD_DIR when explicitly configured. Save to Notes creates an
ordinary owned note tagged `quick-capture`; it clears only the saved draft after
the note commit succeeds. Revision checks and retry receipts protect competing
windows and interrupted conversions. Back up the Markdown, ownership/revision
metadata and conversion receipts together with app.db. No existing database
schema or saved content is migrated.

System diagnostics reports current Exodus-process RSS, available space on the
data filesystem, real local Notes/Calendar/mail-cache read probes, and the
existing Vaultwarden health probe. A readable mail cache does not establish a
working IMAP/SMTP connection, and Vaultwarden health does not prove device sync.
Measurements refresh on demand and dashboard activity; no widget data-polling
interval is added. Team sharing and announcements remain available in details.
All of these features work in both workspace modes without a model or embedding
requirement. Remote email arrival still requires the existing mail sync path;
the event bus reacts immediately once that path updates the local cache.

Verification uses disposable local databases and an isolated full-UI fixture.
The focused Python suites cover committed CRUD events, rollback and owner
isolation, scratchpad persistence/conflicts/retries, local telemetry and existing
Notes, Library, Calendar and Home behavior (61 passing tests). JavaScript tests
cover event coalescing, reconnects, autosave/recovery, live form preservation and
the existing email/calendar handlers (19 passing tests). Browser checks in both
workspace modes cover capture, reload persistence, Save to Notes and reactive
widget updates without a page reload. Email cache events are tested locally;
this dashboard change does not constitute a live IMAP delivery test.


## Invitation-only ecosystem (2026-10-01)

The first Exodus account is administrator; subsequent people join with expiring,
revocable single-use invitations and choose their own passwords. Settings → Team
& invitations extends existing user/role controls. Invitation-only mode enforces
authentication, closes legacy public signup, and retains existing accounts/data.
Non-AI personal features work in both modes. Preferences and logo selection are
saved per account; container addresses and server policy stay administrator-owned.
Never copy another member's credentials, settings, private content, or vault CLI
session as new-user defaults. Keep service access/invitation/exit guidance visible.

Vaultwarden keeps its separate account/master password per user, as explicitly
approved. Its public signup is disabled and native invitations remain available;
Exodus links to native vault administration without receiving the admin secret.
Optional CLI sessions/config and CLI app data are owner-scoped; old shared CLI
state is preserved but never inherited by named users. Logout/removal in Exodus
is not logout/removal in Vaultwarden. Users must be told to revoke both services.
The current Mac-only deployment is not a production multi-tenant deployment:
shared ntfy topics, admin-only Harness, and other shared infrastructure are not
private per-account services. Every future integration needs explicit ownership,
settings, onboarding/offboarding, and cross-user tests. See docs/TEAM_ACCOUNTS.md.

## Verified AI-free ordinary operations

Reminders, supported non-AI integration setup/tests and the Automations view
remain available in both modes. AI-free reminders deliver the original note
text even when AI synthesis was previously enabled; background delivery carries
the note owner's policy. Existing admin and account checks remain unchanged.
The scheduler permits only reviewed local housekeeping actions and the plain
daily digest in AI-free mode. Model/research jobs, arbitrary shell actions and
custom tool delivery remain suspended, with their saved definitions/history
intact. Switching modes cancels model jobs, not ordinary maintenance. Unknown
integration presets cannot be tested or enabled through AI-free configuration;
known ntfy, feeds, git, bookmarks, smart-home and vault presets remain available.
Explicit ordinary-job notification output delivers owner-scoped browser notices
in both modes; quiet or muted housekeeping remains quiet.
The native ntfy fallback is port 8091, matching the local stack.
