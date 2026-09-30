// Code uses the same service dialog and tab preference as the other companions.
export function initCodeDetails(body) {
  const status = body.querySelector('#code-status');
  const list = body.querySelector('#code-models');
  const launch = body.querySelector('#code-launch');
  const refresh = body.querySelector('#code-refresh');
  let stopped = false, busy = false;
  async function request(path, method = 'GET') {
    const response = await fetch('/api/code/' + path, {method, credentials: 'same-origin', cache: 'no-store'});
    const data = await response.json();
    if (!response.ok) throw new Error(typeof data.detail === 'string' ? data.detail : 'Code is unavailable. Sign in as an administrator.');
    return data;
  }
  async function update() {
    if (busy || stopped) return;
    busy = true; refresh.disabled = true;
    try {
      await request('connect', 'POST');
      const data = await request('status');
      if (stopped) return;
      launch.hidden = !data.running;
      if (data.launch_url) launch.href = data.launch_url;
      status.textContent = !data.running ? 'Harness is not responding. Start its service in Docker, then refresh.' :
        data.models.length ? `Harness is running. ${data.models.length} model(s) available from Exodus; ${data.synced_count} synchronized to Harness.` :
        'Harness is running. No coding model is connected yet. Add a model in Exodus Settings when you are ready; you can explore the workspace now.';
      list.replaceChildren(...data.models.map(m => {
        const item = document.createElement('li'); item.textContent = m.name; return item;
      }));
      list.hidden = !data.models.length;
    } catch (error) {
      if (!stopped) { status.textContent = error.message; launch.hidden = true; list.replaceChildren(); }
    } finally { busy = false; refresh.disabled = false; }
  }
  refresh.addEventListener('click', update);
  body.querySelector('#code-model-settings').addEventListener('click', async () => {
    const settings = await import('../settings.js?v=sovereign-essentials1');
    body.closest('.modal')?._dismiss?.();
    settings.open('services');
  });
  update();
  const timer = setInterval(update, 5000);
  return () => { stopped = true; clearInterval(timer); };
}
