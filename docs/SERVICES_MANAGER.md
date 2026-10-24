# Services manager

Settings → System → **Services** lets an admin manage the optional services
that run next to Exodus: SearXNG, ChromaDB, ntfy, Vaultwarden, Code (DeepSeek
Harness) and the Replica video player.

| Button | What happens |
|---|---|
| **Turn off** | The service stops. Its container and data stay. It stays off, even after `docker compose up`. |
| **Turn on** | Starts it again (or creates it again if it was removed). |
| **Remove** | Deletes its container and image to free disk space. **Data is kept** unless you also tick "delete its data", which removes only its Docker volumes. Folders on the computer (for example `data/vaultwarden`) are never deleted. |
| **Install** / **Reinstall** | Downloads (or builds) it again and turns it on. |

The Exodus app itself is never on the list, so it can't be switched off by mistake.

## Turning it on (one-time)

The Services manager needs access to Docker, so it is an **opt-in add-on**. A
small helper container (`servicectl`) does the Docker work. It only accepts a
fixed list of actions on the services above, needs a secret token the app
reads, and is not reachable from outside the computer.

1. In the Exodus folder, add this line to `.env` (or extend your existing
   `COMPOSE_FILE` line):

   ```
   COMPOSE_FILE=docker-compose.yml:docker-compose.override.yml:docker/service-manager.yml
   ```

2. Run `docker compose up -d`.
3. Open Settings → System → Services.

Without the add-on, the Services card says it is off and shows these steps.

## Hiding apps (everyone)

Each person can hide apps and sections they don't use in Settings →
Appearance → **Sidebar**: Email, Calendar, Clock, Calculator, AI Workshop,
Code, Local Services, Privacy Hub and more. Hiding only changes that person's
menus. It is saved with their account, so it follows them to every device.
Built-in apps added later get a switch automatically.

## Files

- `services/servicectl/` — the helper (Python standard library + Docker CLI).
- `docker/service-manager.yml` — the opt-in add-on.
- `routes/services_routes.py` — admin-only API at `/api/services`.
- `static/js/settings/servicesManager.js` — the Settings card.
