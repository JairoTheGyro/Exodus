# Exodus cloud development and local testing

Source of truth: the private `JairoTheGyro/Exodus` repository, branch `main`.
The Mac remains the live development installation. Moving code work to Codex
Cloud does not move Docker Desktop, local accounts, databases or uploaded files.
It also does not migrate this chat's complete history: `AGENTS.md`,
`SOVEREIGN_PRINCIPLES.md` and the repository docs carry the engineering context.

Verified on 2026-10-01: the real Codex Cloud setup completed all 17 focused suites
at commit `61e75cab`, as did GitHub's Linux CI. That run covered 109 Python checks
and four Node harnesses. Subsequent updater fixes add four more unit checks for
Docker Desktop storage representations. The cloud `command -v docker` probe
returned no executable; no cloud Docker containers or live browser tests were run.

## Configured cloud environment

Use **Exodus — development**:
https://chatgpt.com/codex/cloud/settings/environment/6abecc46166c8191b7b50985665efc2b

The account's current interface uses the classic Codex environment editor:

- Repository: `JairoTheGyro/Exodus`; select `main` when starting work.
- Image: `universal`; Python 3.11; Node 22.
- Setup script:
  ```sh
  set -e
  bash scripts/cloud_setup.sh
  .venv/bin/python scripts/cloud_test.py
  ```
- Maintenance script: `bash scripts/cloud_setup.sh`.
- Agent internet: Off. Setup/maintenance can install dependencies. Tests use
  synthetic data and mocked providers; no production secrets are configured.
- Post-setup cache: On. Setup installs only the focused test dependencies, not
  the full runtime, Docker stack, embedding models or model weights.

To reproduce the connection in this interface:

1. Open https://chatgpt.com/codex/cloud and sign in. Open the environment/repository
   selector and choose **Configure Repositories on GitHub** if Exodus is absent.
2. Complete GitHub verification; grant the Codex connector access to the private
   `JairoTheGyro/Exodus` repository. Prefer selected-repository access.
3. Choose **Create environment**, select Exodus, then open its **Edit** page.
   Set the runtime versions and scripts above; save the environment.
4. Select **Exodus — development** and `main` in the task composer. Ask Codex to
   read the project instructions, run the focused tests, and work on a task branch.

Newer accounts may instead show **Work in > Cloud > Create environment** and an
install-script/start-skill setup conversation followed by **Publish**. Use the
same commands. These are two interfaces to configure, not repository files that
automatically register an account's cloud environment.

## Test layers and what they prove

| Layer | Command or workflow | Scope |
| --- | --- | --- |
| Portable baseline | `.venv/bin/python scripts/cloud_test.py` | Real route/model logic, temporary SQLite, notes, library, calendar, Home, mail TLS/templates, Vaultwarden health routes, controlled JS UI harnesses |
| Focused subset | `.venv/bin/python scripts/cloud_test.py --suite notes-search` | One suite; repeat `--suite` for more |
| GitHub CI | `Exodus offline baseline` | The same baseline on fresh Linux/Python 3.11/Node 22 |
| Existing upstream CI | Existing `CI`, security and build workflows | Kept intact; the focused baseline does not replace them |
| Disposable Docker E2E on Mac | `python3 tests/vaultwarden_e2e.py` and `python3 tests/vaultwarden_tls.py` | Real vault/gateway containers, ports, headers, WebSockets, restart persistence, outage and TLS rejection; synthetic volumes only |
| Live acceptance on Mac | Open `http://localhost:7070/` | Actual browser rendering in both modes and configured local services/accounts |

The baseline runs each Python suite in a separate process and temporary working
directory. It explicitly disables dotenv loading, strips inherited credentials,
isolates database/document/cache paths and blocks external Python sockets.
Node harnesses use controlled DOM/fetch implementations; they are not browser
rendering tests. Existing standalone `*_integration.py` tests are invoked
explicitly because default pytest discovery does not collect them.

Cloud Linux can run Python/FastAPI and temporary SQLite tests. A disposable app
server and browser tests require installing the full runtime/browser tools and
configuring synthetic accounts, not copying Mac state. The minimal setup does
not claim to start the full app. Cloud `localhost` refers to the cloud machine.

Do not assume Docker works merely because `docker` is installed. Probe
`docker info` and `docker compose version`; a reachable daemon, permitted nested
containers, image access, compatible architecture and sufficient resources are
required. Our cloud baseline needs none of those. Keep full Compose and native
browser acceptance on the Mac unless the actual cloud environment passes these
capability checks. Cloud is a development sandbox, not the deployed Exodus host.

## Git workflow

Cloud tasks start from current `origin/main`, use `codex/<task>` branches, run the
baseline plus tests relevant to the change, and commit source/tests. Publish via
Codex's **Create PR** action; GitHub merge is the step that updates `origin/main`.
The cloud shell may not have GitHub push credentials, so do not assume that a
plain `git push` is available there and do not upload a personal token to fix it.

For an authenticated Git checkout, the equivalent branch workflow is:

```sh
git fetch origin main
git switch -c codex/your-change origin/main
# Make and test the change, then stage only reviewed files.
git add <reviewed-source-and-test-files>
git commit -m "describe the completed change"
git push -u origin codex/your-change
```

Open a PR against `main`, review its diff and tests, then merge it in GitHub.
Direct `git push origin main` is only appropriate for an explicitly authorized,
tested fast-forward from an authenticated checkout. Never force-push `main`.
This workflow is documented guidance; it does not turn on GitHub branch protection.

The single Mac command after merging is:

```sh
python3 "/Users/jairoperalta/Documents/Codex/Sovereign Solutions/Sovereign Hub/scripts/update_local.py"
```

The updater requires a clean `main`, verifies the GitHub destination and Docker,
fetches and accepts only a fast-forward, then pulls with `--ff-only`. It examines
the actual Compose mounts/overlays, rebuilds affected image inputs when needed,
and recreates affected services with their existing volumes. Mounted source
changes do not require rebuilding dependencies. Refresh the browser tab after
UI changes; the script does not inject browser reload code into Exodus.

Use `--dry-run` to fetch metadata and inspect the planned work without changing
the checkout or containers. Persistent mount/network removal or replacement
stops the update for a separate migration review. A failed deployment retains a
checkpoint so rerunning can apply the already-pulled source. The updater does
not reset changes, stash work, delete volumes, prune Docker or pull `latest` on
every run. Keep Docker Desktop running while updating/testing on the Mac.

## Avoid conflicts and keep data private

- Prefer the cloud as the active code editor while the Mac runs `main`. For a
  local fix, start a separate task branch, commit and publish it; merge before
  starting the next cloud change. Do not edit the same files concurrently.
- `.gitignore` excludes `.env*`, all `data/` and `chroma_data/` directories,
  SQLite databases/sidecars, backups, credentials and model weights. Verify
  tracked files as well: ignore rules do not untrack previously committed files.
- Docker named volumes never go into Git. The existing Mac data and `.env` remain
  in place during a code pull. A fresh cloud checkout gets no copy of them.
- Schema/data migrations still need compatibility tests and a private backup
  before applying to real data. Git conflict avoidance is not a database backup.
- Test normal features in both Full and AI-Free modes. Only explicitly AI
  capabilities depend on models. Never use AI calls to implement local filtering,
  counting, sorting or similar deterministic operations.

## Known CI baseline at handoff

The previous main commit already had failures in the broad upstream suite,
including stale branding assertions, Compose parity and test-fixture/router
assumptions. The Docker publish workflow used uppercase repository names, and
CodeQL/dependency review reported missing private-repository feature support.
These are separate follow-up work, not silently disabled by this migration.
Check the exact latest run in GitHub Actions before treating a PR as fully green.

Official setup references:
[Cloud overview](https://learn.chatgpt.com/docs/cloud),
[current environments](https://learn.chatgpt.com/docs/environments/cloud-environments),
[classic environment editor](https://learn.chatgpt.com/docs/environments/cloud-environment).
