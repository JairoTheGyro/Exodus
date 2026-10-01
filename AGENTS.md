# Sovereign Solutions

Read `SOVEREIGN_PRINCIPLES.md` before changing product behavior.

- Keep Odysseus as the shared interface and foundation.
- Inspect existing code before adding a feature. Extend or connect existing
  functionality instead of creating duplicates.
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

## Cloud and local development

- Read `docs/CLOUD_DEVELOPMENT.md` for setup, test scope and the Git handoff.
- Cloud tasks use their provisioned checkout. Do not try to reach the Mac's
  localhost or copy its `.env`, databases, documents or Docker volumes.
- Non-AI features must work in both Full and AI-Free modes. Test both where
  relevant; AI-Free is not a separate codebase or a reason to hide ordinary tools.
- Run `bash scripts/cloud_setup.sh` during environment installation, then
  `.venv/bin/python scripts/cloud_test.py` for the isolated regression baseline.
  Also run focused tests for changed behavior. This baseline is not the full
  upstream test suite or proof of real provider/container behavior.
- Work on a `codex/<task>` branch from current `origin/main`. Commit source and
  tests, publish a pull request, and report exact checks and remaining limits.
  Merge after review; do not force-push main or silently resolve divergence.
- Never run broad tests against the operator's live data. Keep synthetic data
  and disposable service volumes separate from the `sovereign-hub` deployment.
- Do not claim Docker, browser automation, model calls, mail delivery or device
  sync passed unless actually exercised in that environment. Probe capabilities
  first, and report skipped checks with their reason.
- Before an update changes a persistent schema, document the migration and
  backup/restore plan. Git backs up source, not local runtime data.
