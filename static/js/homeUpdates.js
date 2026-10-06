// Coalesce invalidations, not data: authoritative values still come from local APIs.
export const topicWidgets = Object.freeze({
  notes:['tasks','metrics','files'], documents:['files'], calendar:['schedule'], inbox:['inbox','files'],
  profile:['apps','metrics','team','weather'], goals:['metrics'], focus:['focus','metrics'], team:['team'], scratchpad:['capture'],
});
export function createHomeUpdates({subscribe, refresh, refreshProfile, allWidgets, schedule=setTimeout, cancel=clearTimeout}) {
  let pending = new Set(), profilePending = false, timer, stopped = false;
  const enqueue = topic => {
    if (stopped) return;
    if (topic === 'reconnect') { allWidgets.forEach(id => pending.add(id)); profilePending = true; }
    else { (topicWidgets[topic] || []).forEach(id => pending.add(id)); if (topic !== 'scratchpad') pending.add('team'); if (topic === 'profile' || topic === 'goals') profilePending = true; }
    cancel(timer); timer = schedule(drain, 70);
  };
  async function drain() {
    const ids = [...pending], needsProfile = profilePending;
    pending.clear(); profilePending = false;
    if (needsProfile) await refreshProfile();
    if (!stopped) for (const id of ids) refresh(id);
  }
  const unsubscribers = [...Object.keys(topicWidgets), 'reconnect'].map(topic => subscribe(topic, () => enqueue(topic)));
  return {enqueue, stop() { stopped=true; cancel(timer); unsubscribers.forEach(fn=>fn()); }, flush:drain};
}
// Per-view response sequencing also protects against failures from obsolete requests.
export function createResponseGuard() {
  const versions = new WeakMap();
  return element => {
    const sequence = (versions.get(element) || 0) + 1;
    versions.set(element, sequence);
    return () => versions.get(element) === sequence && element.isConnected;
  };
}
