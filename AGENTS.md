# Sovereign Solutions

Read `SOVEREIGN_PRINCIPLES.md` before changing product behavior.

- Keep Odysseus as the shared interface and foundation.
- Inspect existing code before adding a feature. Extend or connect existing
  functionality instead of creating duplicates.
- Team onboarding is first administrator, then invitations. Follow
  `docs/TEAM_ACCOUNTS.md`: personal data/settings belong to the signed-in account;
  shared infrastructure stays admin-managed. Never inherit another account’s
  credentials or vault session. Every integration must document invitations,
  removal, personal/shared scope and cross-account tests in both modes.
- Do not delete existing features. Simpler views must keep a clear route to
  deeper controls, and existing direct links must continue to work.
- Explain consequential decisions in plain language. The user is learning.
- Use real functionality and honest status. Do not invent usage, savings,
  connected models, or successful operations.
- Work in this existing checkout; do not clone or duplicate it for convenience.
  Preserve saved data and credentials, and do not print secrets in summaries.
- For the mounted UI files, refresh the browser to preview changes. Avoid
  rebuilding dependencies for interface-only edits. Other source changes may
  require a rebuild; inspect the Compose configuration first.

## Active workflow: fully local

- The user requests a feature; implement and verify it in this existing local
  checkout and Docker installation; then let the user test it in Exodus.
- Every feature or fix follows branch → commit → pull request → merge:
  1. Pull the latest `main` from GitHub, then create a descriptively named
     branch for the work (for example `feat/notes-search`).
  2. Implement, verify and commit on that branch; push it to GitHub. While the
     branch is checked out, the running Exodus shows the in-progress change, so
     the user can test it before it is merged.
  3. Open a pull request into `main` that explains the change in plain language.
  4. Merge the pull request, then switch this checkout back to `main` and pull,
     so the self-hosted copy and GitHub match again.
  5. Update the running self-hosted Exodus so it serves the merged `main`:
     refresh for UI-only changes, restart the app for mounted Python changes,
     and rebuild for dependency or image changes (inspect the Compose
     configuration first). Then confirm the running version matches `main`.
  No separate permission is needed for any of these steps. Never commit directly
  to `main`. Do not move work into a cloud environment unasked.
- The workflow covers both copies, the self-hosted checkout and Docker
  deployment on the Mac and the GitHub repository, in both directions:
  - Changes that start on the Mac (uncommitted edits, work by another tool or
    helper) go onto a branch and through a pull request; never leave them
    unsaved or push them straight to `main`.
  - Changes that start on GitHub (merged pull requests, Dependabot updates,
    edits made on github.com) are pulled to the Mac and applied to the running
    Exodus as in step 5.
  - At the start and end of every task, compare local `main`, GitHub `main`
    and the running deployment, and report any difference. If the two copies
    have diverged, stop and explain rather than overwrite either side.
- Give each commit a specific, descriptive subject naming the feature or module
  discussed and the concrete change, so the history is easy to track. Avoid
  generic subjects such as "updates" or "fixes". Honor an exact commit message
  when the user provides one.
- Cloud migration is no longer the active plan. Keep the prepared cloud helpers
  as optional tooling, but do not start cloud tasks or migrate services/data
  unless the user explicitly asks to resume that work.
- Non-AI features must work in both Full and AI-Free modes. Test both where
  relevant; AI-Free is not a separate codebase or a reason to hide ordinary tools.
- Run focused tests appropriate to the change. The optional isolated runner
  `scripts/cloud_test.py` also works locally with its test dependencies installed;
  its name does not require using a cloud service. It is not the full upstream
  suite or proof of real provider/container behavior.
- Keep `docs/PRACTICE_TESTS.md` current with a real-life acceptance check for each
  added or changed feature: synthetic inputs, prerequisites/modes, expected saved
  and visible results, and cleanup. Report actual execution separately from the
  reusable procedure; never label an unrun live/device check as passed.
- Do not force-push or silently resolve Git divergence.
- When pushing a change, report three separate verified checks:
  saved locally, running and checked in Docker, and pushed to GitHub. Compare
  deployed source with the checkout and local HEAD with remote main; a Git push
  alone does not update running containers. Keep this iCloud-backed checkout
  downloaded locally so Docker bind mounts can read it reliably.
- Do not claim Docker, browser automation, model calls, mail delivery or device
  sync passed unless actually exercised in that environment. Probe capabilities
  first, and report skipped checks with their reason.
- Before an update changes a persistent schema, document the migration and
  backup/restore plan. Git backs up source, not local runtime data.
