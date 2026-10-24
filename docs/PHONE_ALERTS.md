# Phone alerts

Exodus sends reminders and alerts to phones through **ntfy**, a small push
service that runs next to Exodus. Each account has its own **private
address** (an ntfy "topic"), so people only get their own alerts.

## Add Exodus to your home screen

Exodus works like an app on phones:

- **iPhone:** open Exodus in **Safari**, sign in, tap **Share**, then **Add to
  Home Screen**.
- **Android:** open it in **Chrome**, then tap **⋮** → **Install app** (or
  **Add to Home screen**).

The icon opens Exodus full screen, without the browser bars. It's named after
your workspace (Settings → System → workspace name). Adding it from the
sign-in page works too.

## Set up your phone

Settings → Account → **Phone alerts** shows your server and topic.

1. Install the free **ntfy** app (Android or iPhone).
2. Tap **+**, turn on **Use another server**, and enter the server shown.
3. Enter your topic and subscribe.
4. Press **Send test** in Exodus.

Your topic is a long random name, such as `exodus-Xb3…`. ntfy has no
passwords here: **anyone who knows the topic can read it**, so don't share it.
If it leaks, press **Get a new address** and subscribe to the new one.

## What goes there

- **Reminders**, when Settings → Reminders → channel is set to ntfy.
- **Alerts** from the AI's "notify me" tool (admins).

Other people's reminders never go to your topic.

## For the admin

- **Reaching ntfy from phones.** By default ntfy only listens on the Exodus
  computer itself (`NTFY_BIND=127.0.0.1`). For phones, set `NTFY_BIND` to the
  computer's private-network address (for example its Tailscale IP) and
  `NTFY_PUBLIC_URL` to the same address with port 8091, then restart. Settings
  shows `NTFY_PUBLIC_URL` to everyone as the server.
- **Single-user installs** (no sign-in accounts) keep the shared topics:
  `NTFY_DEFAULT_TOPIC` for alerts and the Reminders topic setting.
- **Upgrading from shared topics.** Anyone subscribed to the old shared
  "Reminders" or "exodus-alerts" topic must subscribe to their new private
  topic instead.
- Topics are stored with each account's preferences (key `exodus_ntfy_topic`),
  so an account rename keeps it.

## Files

- `src/personal_alerts.py`: creates and keeps each account's topic.
- `src/notifications.py`: sends to the account's topic.
- `routes/personal_alerts_routes.py`: `/api/alerts/phone` (status, test, new address).
- `static/js/settings/phoneAlerts.js`: the Settings card.
- `tests/test_personal_alerts.py`: tests.
