# Go-public audit (2026-10-22)

Checks done before making `JairoTheGyro/Exodus` public. Scope: everything
pushed to the Exodus repository (`main`, `pr-assets` and remaining branches;
2,639 commits, about 19,400 file versions, no tags). The Odysseus history it
contains is already public upstream.

## Results

| Check | Result |
|---|---|
| Files ever pushed | Only code, docs, tests and example settings. No `.env`, databases, backups, logs, private keys or session files in any commit. |
| Secret patterns in every file version (private keys, cloud/AI/GitHub/Slack/Stripe/HF tokens, JWTs, password hashes, `password = "…"` style assignments) | Only made-up test values and style-snapshot fingerprints. The four entries in `.gitleaksignore` were re-checked and are not secrets. |
| Real local secrets searched for by exact value (`data/.app_key`, the account password hash in `data/auth.json`, Vaultwarden RSA and TLS keys, `.env` values) | None appear anywhere in the history. |
| Personal details in Exodus's own changes (emails, phone numbers, street addresses, home-network addresses, home folder paths) | One home folder path in `docs/CLOUD_DEVELOPMENT.md`, now replaced. `192.168.1.3` in a Vaultwarden test is a made-up example. The owner's GitHub username appears in repo URLs (public anyway). |
| Commit identities | Exodus commits carry the author name and a machine-generated address (`…@Jairos-MacBook-Air.local`, not a real mailbox); GitHub web merges use the private `users.noreply.github.com` address. No personal email address appears. See "Owner decisions". |
| Images | Only the Exodus icon and PR screenshots taken from disposable test copies (test account, test notes). |
| Licences and credits | AGPL modification notice added to the top of `README.md`. `ACKNOWLEDGMENTS.md` now credits Vaultwarden, DeepSeek Harness, the TempleOS font (public domain), Natural Earth map data (public domain) and ExchangeRate-API; it also states that Calculator and Clock are original recreations without Apple code or assets. The Calculator links to ExchangeRate-API as its free terms ask. |
| GitHub settings | No Actions secrets, variables, deploy keys, webhooks or environments. Workflow token defaults to read-only and cannot approve PRs. Only one collaborator. The one `pull_request_target` workflow checks out the base branch only, so it never runs a fork's code. |

## Owner decisions before flipping

1. **Author name on commits.** The full name stays visible in public commit
   history unless the history is rewritten (all Exodus commit IDs change and
   `main` must be force-pushed once). Keeping it is normal for open-source work.
2. **Make the repository public** (GitHub → Settings → General → Danger Zone →
   Change visibility), or ask Claude to do it.

## Right after it goes public

- Turn on branch protection for `main` (block force-pushes and deletion).
- Turn on secret scanning with push protection, Dependabot alerts and private
  vulnerability reporting.
- Confirm the checks that skip private repos run again (CodeQL, dependency
  review, Trivy) and that the next pull request's checks pass.
