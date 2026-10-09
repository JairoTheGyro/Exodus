// Render upstream content as text, never as trusted HTML or executable Markdown.
let loading = false;
const node = (tag, value, className) => {
  const element = document.createElement(tag);
  if (value !== undefined) element.textContent = value;
  if (className) element.className = className;
  return element;
};
const link = (label, url) => {
  const element = node('a', label);
  element.href = url;
  element.target = '_blank';
  element.rel = 'noopener noreferrer';
  return element;
};
const date = value => value ? new Date(value).toLocaleString() : 'Not checked yet';
const short = sha => sha.slice(0, 8);

async function request(url, method = 'GET') {
  const response = await fetch(url, { method, credentials: 'same-origin' });
  const data = await response.json();
  if (!response.ok) throw new Error(typeof data.detail === 'string' ? data.detail : 'Could not load update history.');
  return data;
}

function action(label, run, enabled = true) {
  const button = node('button', label, 'upstream-button');
  button.type = 'button';
  button.disabled = !enabled;
  button.addEventListener('click', async () => {
    button.disabled = true;
    try { await run(); } finally { button.disabled = !enabled; }
  });
  return button;
}

function comparisonText(snapshot) {
  const c = snapshot?.comparison;
  if (!c) return snapshot?.comparison_error ? `Comparison unavailable: ${snapshot.comparison_error}` : 'Check for updates to compare revisions.';
  if (c.status === 'identical') return 'The tracked branch matches our upstream baseline. Exodus still has its own local modifications.';
  if (c.status === 'ahead') return `${c.ahead_by} upstream commits after our baseline. This does not mean ${c.ahead_by} new features or required updates.`;
  if (c.status === 'behind') return 'The tracked branch is behind our recorded baseline. Review the branch before drawing update conclusions.';
  return 'The histories have diverged. A code review is needed; this is not a simple behind/ahead comparison.';
}

function renderProject(entry, canCheck) {
  const p = entry.project;
  const repo = `https://github.com/${p.repository}`;
  const api = `/api/upstream/${encodeURIComponent(p.id)}`;
  const card = node('article', undefined, 'upstream-project');
  const status = node('p', '', 'upstream-status');
  status.setAttribute('role', 'status');
  let records = [];
  let details = new Map();
  let page = 1;
  let busy = false;

  const report = () => {
    const s = entry.snapshot;
    const lines = [`${p.name} — upstream review`, `Repository: ${repo}`, `Tracked branch: ${p.branch}`,
      `Exodus upstream baseline: ${p.used_version || 'Unnumbered'} / ${p.used_commit} (${p.used_date})`, p.used_note,
      p.observed_at ? `Installation observed: ${p.observed_at}` : '',
      p.used_image ? `Recorded container image: ${p.used_image}` : '',
      `Latest checked declared version: ${s?.version || 'Not available'}`,
      `Latest checked revision: ${s?.head || 'Not checked'}`, `Last successful check: ${s?.checked_at || 'Never'}`,
      `Last attempt: ${entry.last_attempt || 'Never'}`, entry.error ? `Last check error: ${entry.error}` : '',
      comparisonText(s), s ? `Compare: ${repo}/compare/${p.used_commit}...${s.head}` : '',
      '\nThis report is public upstream information, not a compatibility verdict. Nothing has been installed.',
      'Only the loaded commits, releases, and file details are included. Please review relevance, overlap, dependencies, and risks before integration.',
      '\nRELEASE NOTES'];
    for (const r of s?.releases || []) lines.push(`\n${r.tag} — ${r.name} (${r.date || 'undated'})${r.prerelease ? ' [prerelease]' : ''}`, r.notes || 'No release notes supplied.', r.notes_truncated ? 'Notes shortened; see the full release on GitHub.' : '');
    lines.push('\nLOADED COMMITS');
    for (const c of records) {
      lines.push(`\n${c.sha} (${c.date || 'undated'})`, c.message, `${repo}/commit/${c.sha}`);
      const d = details.get(c.sha);
      if (d) {
        for (const f of d.files) lines.push(`${f.status}: ${f.name}${f.previous_name ? ` (from ${f.previous_name})` : ''} (+${f.additions}/-${f.deletions} lines)`);
        if (d.more_files) lines.push('Additional files omitted; see full change on GitHub.');
      }
    }
    const url = URL.createObjectURL(new Blob([lines.filter(Boolean).join('\n')], { type: 'text/plain;charset=utf-8' }));
    const a = node('a'); a.href = url; a.download = `${p.id}-update-review.txt`; a.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
    status.textContent = 'Review report prepared for download. You can share the saved file with Codex for review.';
  };

  const cachedOrOnline = async path => {
    try { return await request(path); }
    catch (error) { if (!canCheck) throw error; return request(path, 'POST'); }
  };

  const commitRow = c => {
    const row = node('details', undefined, 'upstream-change');
    row.append(node('summary', `${short(c.sha)} · ${c.message.split('\n')[0]}`), node('p', date(c.date)), node('p', c.message, 'upstream-notes'));
    const files = node('div');
    row.append(link('View full change on GitHub', `${repo}/commit/${c.sha}`));
    row.append(action(canCheck ? 'Load file changes' : 'View saved file changes', async () => {
      files.textContent = 'Loading file changes…';
      try {
        const d = await cachedOrOnline(`${api}/commits/${c.sha}`);
        details.set(c.sha, d);
        files.replaceChildren(node('p', 'File changes describe source code, not necessarily added or removed features.'));
        const list = node('ul', undefined, 'upstream-files');
        for (const f of d.files) list.append(node('li', `${f.status}: ${f.name}${f.previous_name ? ` (from ${f.previous_name})` : ''} · +${f.additions} / −${f.deletions} lines`));
        files.append(list);
        if (!d.files.length) files.append(node('p', 'No file changes were returned for this revision.'));
        if (d.more_files) files.append(node('p', 'Showing the first 100 files. Open the full change on GitHub for the remainder.'));
      } catch (error) { files.textContent = error.message; }
    }), files);
    return row;
  };

  function draw() {
    const s = entry.snapshot;
    records = [...(s?.commits || [])]; details = new Map(); page = 1;
    card.replaceChildren(node('h4', p.name));
    const info = node('dl', undefined, 'license-tracker-details');
    const field = (label, content) => { const row = node('div'); const value = node('dd'); value.append(content); row.append(node('dt', label), value); info.append(row); };
    field(p.observed_at ? 'Recorded release reference' : 'Used as our base', link(`${p.used_version ? p.used_version + ' · ' : ''}${short(p.used_commit)} · ${p.used_date}`, `${repo}/commit/${p.used_commit}`));
    if(p.observed_at)field('Installation verified',node('span',p.observed_at));
    if(p.used_image){const image=node('code',p.used_image);image.style.overflowWrap='anywhere';field('Recorded image',image);}
    field('Tracked branch', node('span', p.branch));
    field('Latest checked revision', s ? link(short(s.head), `${repo}/commit/${s.head}`) : node('span', 'Not checked yet'));
    field('Latest declared version', node('span', s?.version || (s ? 'Not available — use the exact revision above' : 'Not checked yet')));
    field('Last successful check', node('span', date(s?.checked_at)));
    if (entry.last_attempt && entry.last_attempt !== s?.checked_at) field('Last attempt', node('span', date(entry.last_attempt)));
    card.append(info, node('p', p.used_note), node('p', comparisonText(s)));
    const buttons = node('div', undefined, 'license-tracker-links');
    buttons.append(action('Check for updates', async () => {
      if (busy) return;
      busy = true; status.textContent = 'Checking GitHub…';
      try { entry = await request(`${api}/check`, 'POST'); draw(); }
      catch (error) { status.textContent = error.message; }
      finally { busy = false; }
    }, canCheck), action('Download review report', report, !!s));
    if (s) buttons.append(link('Compare baseline with latest', `${repo}/compare/${p.used_commit}...${s.head}`));
    card.append(buttons, status);
    status.textContent = entry.error || (s ? 'Saved snapshot shown. Use Check for updates to refresh it.' : 'No update check has been made.');
    if (!canCheck) card.append(node('p', 'An administrator can check GitHub. Saved results are available to you.'));
    if (!s) return;

    card.append(node('h4', 'Published releases'));
    if (!s.releases.length) card.append(node('p', 'No published releases were returned by GitHub. The commit history below still tracks code changes.'));
    else card.append(node('p', 'Recent releases in GitHub’s ordering. Release tags and development-branch revisions are different; a release is not automatically installed or compatible.'));
    for (const release of s.releases) {
      const item = node('details', undefined, 'upstream-change');
      item.append(node('summary', `${release.tag} · ${release.name || release.tag}${release.prerelease ? ' (prerelease)' : ''}`),
        node('p', date(release.date)), node('p', release.notes || 'No release notes supplied.', 'upstream-notes'),
        link('View release', `${repo}/releases/tag/${encodeURIComponent(release.tag)}`));
      if (release.notes_truncated) item.append(node('p', 'Notes shortened to 20,000 characters. Open the release for the full text.'));
      card.append(item);
    }
    card.append(link('All releases on GitHub', `${repo}/releases`));
    card.append(node('h4', 'Code change history'), node('p', 'Newest first at the checked revision. These are the authors’ descriptions; additions and removals may require inspecting the linked code. History includes older changes that may already be in our baseline.'));
    const list = node('div'); records.forEach(c => list.append(commitRow(c))); card.append(list);
    const older = action(canCheck ? 'Load older' : 'Load saved older history', async () => {
      status.textContent = 'Loading older history…';
      try {
        const result = await cachedOrOnline(`${api}/history?page=${page + 1}`);
        page += 1; records.push(...result.commits); result.commits.forEach(c => list.append(commitRow(c)));
        older.hidden = !result.more;
        status.textContent = `${records.length} commits loaded. Recent loaded pages are saved for offline viewing.`;
      } catch (error) { status.textContent = error.message; }
    });
    older.hidden = !s.more_commits;
    card.append(older, link('Full branch history on GitHub', `${repo}/commits/${encodeURIComponent(p.branch)}`));
  }
  draw();
  return card;
}

export async function loadUpstreamUpdates() {
  const root = document.getElementById('upstream-updates');
  if (!root || loading) return;
  loading = true;
  root.textContent = 'Loading saved update history…';
  try {
    const data = await request('/api/upstream');
    root.replaceChildren(...data.projects.map(entry => renderProject(entry, data.can_check)));
  } catch (error) {
    root.replaceChildren(node('p', `Could not load saved history: ${error.message}`), action('Retry loading saved history', loadUpstreamUpdates));
  } finally { loading = false; }
}
