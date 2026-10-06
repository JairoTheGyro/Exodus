// Both Home and Privacy Hub use this non-AI companion-service launcher.
const localHosts = new Set(['localhost', '127.0.0.1', '[::1]']);

function launchSafety(config) {
  let address;
  try { address = new URL(config.vault_url); } catch { return 'The vault address is not configured correctly.'; }
  if (address.username || address.password || config.launch_path !== '/vault') {
    return 'The vault address is not configured correctly.';
  }
  if (localHosts.has(address.hostname) && !localHosts.has(window.location.hostname)) {
    return 'This vault is configured for the computer running Docker. Open Exodus on that computer, or configure a reachable HTTPS vault address for access from another device.';
  }
  if (config.access_mode === 'https' && address.protocol === 'https:') return '';
  if (config.access_mode === 'local' && address.protocol === 'http:' && localHosts.has(address.hostname)) {
    return '';
  }
  return 'A remote vault requires HTTPS. Ask the administrator to configure a secure vault address.';
}

export function initVaultwardenDetails(body) {
  const card = body.querySelector('[data-service-card="vaultwarden"]');
  const status = body.querySelector('#vaultwarden-status');
  const sync = body.querySelector('#vaultwarden-sync');
  const checked = body.querySelector('#vaultwarden-checked');
  const launch = body.querySelector('#vaultwarden-launch');
  const refresh = body.querySelector('#vaultwarden-refresh');
  const diagnostics = body.querySelector('#vaultwarden-diagnostics');
  const startCommand = body.querySelector('#vaultwarden-start-command');
  const address = body.querySelector('#vaultwarden-address');
  const access = body.querySelector('#vaultwarden-access');
  const registration = body.querySelector('#vaultwarden-registration');
  let stopped = false, busy = false, controller;

  const hideLaunch = () => {
    launch.hidden = true;
    // The shared anchor class sets display explicitly, overriding native hidden.
    launch.style.display = 'none';
    launch.removeAttribute('href');
  };
  async function request(path, signal) {
    const response = await fetch('/api/vaultwarden/' + path, {
      credentials: 'same-origin', cache: 'no-store', signal,
    });
    if (!response.ok) {
      throw new Error(response.status === 401 || response.status === 403
        ? 'Sign in to Exodus to check the vault service.'
        : 'Vaultwarden status could not be checked. Check the Exodus server and try again.');
    }
    return response.json();
  }
  async function update() {
    if (busy || stopped) return;
    busy = true;
    refresh.disabled = true;
    card.setAttribute('aria-busy', 'true');
    hideLaunch();
    status.textContent = 'Checking Vaultwarden…';
    sync.textContent = '';
    checked.textContent = '';
    diagnostics.hidden = true;
    address.hidden = true;
    controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), 6500);
    try {
      const [config, health] = await Promise.all([
        request('config', controller.signal), request('status', controller.signal),
      ]);
      if (stopped) return;
      const unsafe = launchSafety(config);
      startCommand.textContent = typeof config.start_command === 'string' ? config.start_command : '';
      address.querySelector('code').textContent = unsafe ? '' : config.vault_url;
      address.hidden = !!unsafe;
      registration.textContent = config.registration_allowed
        ? 'Account creation is temporarily enabled in the deployment settings. Open Vaultwarden and choose Create account to set up your separate vault account. Turn registration off after onboarding; Vaultwarden’s admin settings can override this policy.'
        : config.admin_enabled
          ? 'Open registration is disabled by this deployment’s defaults. An administrator can invite your separate vault account and manage registration policy in Vaultwarden’s admin panel.'
          : 'Open registration is disabled. An administrator must configure secure vault administration before inviting a separate vault account.';
      const timestamp = new Date(health.checked_at);
      if (!Number.isNaN(timestamp.getTime())) checked.textContent = 'Last checked: ' + timestamp.toLocaleString();
      sync.textContent = 'Device sync is shown inside the vault after signing in.';
      if (health.status === 'running' && health.reachable === true) {
        status.textContent = unsafe || 'Vaultwarden is running. Open the vault to access your separate account.';
        if (!unsafe) {
          launch.href = '/vault';
          launch.hidden = false;
          launch.style.display = '';
        }
      } else {
        status.textContent = health.status === 'degraded'
          ? 'Vaultwarden is responding, but is not ready. Check the Vaultwarden container in Docker Desktop.'
          : 'Vaultwarden is offline or unreachable. Start its service, then check again.';
        diagnostics.hidden = !startCommand.textContent;
      }
      access.textContent = unsafe || (config.access_mode === 'local'
        ? 'This saved vault address uses HTTP. Current web-vault versions require HTTPS for account creation and API access, even on this computer. Update the deployment to a trusted HTTPS address.'
        : localHosts.has(new URL(config.vault_url).hostname)
          ? 'The vault opens directly on this computer over HTTPS. Your browser must trust the configured certificate. Access from another device requires a reachable HTTPS vault address.'
          : 'The vault opens directly on its own HTTPS page. A separate page preserves Vaultwarden’s browser security protections.');
    } catch (error) {
      if (!stopped) {
        status.textContent = error.name === 'AbortError'
          ? 'Checking Vaultwarden timed out. Check its container in Docker Desktop, then try again.'
          : error.message.startsWith('Sign in to Exodus') || error.message.startsWith('Vaultwarden status')
            ? error.message : 'Vaultwarden status could not be checked. Check the Exodus server and try again.';
      }
    } finally {
      clearTimeout(timer);
      controller.abort();
      busy = false;
      if (!stopped) { refresh.disabled = false; card.setAttribute('aria-busy', 'false'); }
    }
  }
  refresh.addEventListener('click', update);
  update();
  return () => {
    stopped = true;
    controller?.abort();
    refresh.removeEventListener('click', update);
  };
}
