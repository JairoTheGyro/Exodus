// Exodus shared spaces in Calendar Settings: a "Share to" choice for each
// calendar you made here, and read-only rows for calendars others share with
// you (their events you can still add, edit and delete in the calendar view).
let cached = null;

export async function loadSpaces(fetchImpl = globalThis.fetch) {
  try {
    const r = await fetchImpl('/api/spaces', { credentials: 'same-origin' });
    cached = r.ok ? await r.json() : { me: null, spaces: [] };
  } catch (_) {
    cached = { me: null, spaces: [] };
  }
  return cached;
}

/**
 * Decorate the rows of #cal-settings-list. `calendars` is the list from
 * /api/calendar/calendars; `save(id, spaceId)` changes sharing and resolves
 * when done; `onSaved()` refreshes the calendar.
 */
export function decorateCalendarRows(root, calendars, data, { save, onSaved, toast } = {}) {
  const spaces = (data?.spaces || []).filter(s => s.role);
  const nameOf = id => spaces.find(s => s.id === id)?.name || (data?.spaces || []).find(s => s.id === id)?.name || 'a space';
  for (const row of root.querySelectorAll('.cal-settings-row')) {
    const cal = calendars.find(c => c.href === row.dataset.id);
    if (!cal) continue;
    row.querySelector('.cal-space-note, .cal-s-space')?.remove();
    if (cal.mine === false) {
      // Someone else's calendar shared with you: you can't rename, recolour
      // or delete it, only use it.
      row.classList.add('cal-settings-row-shared');
      row.querySelectorAll('.cal-s-name, .cal-s-color').forEach(input => { input.disabled = true; });
      row.querySelector('.cal-s-del')?.remove();
      // Exporting is for the owner (it's their whole calendar).
      root.querySelectorAll('.cal-s-export-chip').forEach(chip => { if (chip.dataset.id === cal.href) chip.remove(); });
      const note = document.createElement('span');
      note.className = 'cal-space-note';
      note.textContent = `${nameOf(cal.space_id)} · by ${cal.owner}`;
      row.append(note);
      continue;
    }
    if ((cal.source || 'local') !== 'local' || !spaces.length) continue;
    const select = document.createElement('select');
    select.className = 'cal-s-space';
    select.setAttribute('aria-label', `Who can see ${cal.name}`);
    select.title = 'Who can see this calendar';
    const options = [{ id: '', name: 'Only me' }, ...spaces.map(s => ({ id: s.id, name: s.name }))];
    for (const option of options) {
      const el = document.createElement('option');
      el.value = option.id;
      el.textContent = option.name;
      select.append(el);
    }
    select.value = cal.space_id || '';
    select.addEventListener('change', async () => {
      const previous = cal.space_id || '';
      try {
        await save(cal.href, select.value);
        cal.space_id = select.value || null;
        toast?.(select.value ? `Shared with ${nameOf(select.value)}` : 'Now only you can see this calendar');
        onSaved?.();
      } catch (_) {
        select.value = previous;
        toast?.('Could not change who can see this calendar');
      }
    });
    row.querySelector('.cal-s-del')?.before(select);
  }
}
