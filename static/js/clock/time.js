/**
 * Clock — pure time helpers (no DOM). Shared by every Clock view and covered
 * by tests/test_clock_time_js.py.
 *
 * Behaviour notes recovered from macOS Clock.app 1.1 (com.apple.clock):
 *  - Timer presets: MTATimerPresetItem.mockItems.
 *  - Lap colouring: MTAStopwatchLapTableViewController._updateLapExtrema — only
 *    completed laps count, and only once there are at least two of them; the
 *    first fastest / first slowest lap wins a tie.
 */

export const DAY_MS = 86400000;

export const TIMER_PRESETS = [
  { number: 1, unit: 'MIN', seconds: 60 },
  { number: 2, unit: 'MIN', seconds: 120 },
  { number: 3, unit: 'MIN', seconds: 180 },
  { number: 4, unit: 'MIN', seconds: 240 },
  { number: 5, unit: 'MIN', seconds: 300 },
  { number: 10, unit: 'MIN', seconds: 600 },
  { number: 15, unit: 'MIN', seconds: 900 },
  { number: 20, unit: 'MIN', seconds: 1200 },
  { number: 30, unit: 'MIN', seconds: 1800 },
  { number: 45, unit: 'MIN', seconds: 2700 },
  { number: 1, unit: 'HR', seconds: 3600 },
  { number: 2, unit: 'HR', seconds: 7200 },
];

export const WEEKDAY_LETTERS = ['S', 'M', 'T', 'W', 'T', 'F', 'S'];
const WEEKDAY_SHORT = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];

const pad2 = n => String(Math.floor(n)).padStart(2, '0');

/** Stopwatch display: "MM:SS.cc", or "H:MM:SS.cc" from one hour up. */
export function formatStopwatch(ms) {
  const v = Math.max(0, Math.floor(Number(ms) || 0));
  const cs = Math.floor(v / 10) % 100;
  const s = Math.floor(v / 1000) % 60;
  const m = Math.floor(v / 60000) % 60;
  const h = Math.floor(v / 3600000);
  return h > 0 ? `${h}:${pad2(m)}:${pad2(s)}.${pad2(cs)}` : `${pad2(m)}:${pad2(s)}.${pad2(cs)}`;
}

/** Countdown display: "MM:SS", or "H:MM:SS" from one hour up. Rounds up. */
export function formatCountdown(seconds) {
  const v = Math.max(0, Math.ceil(Number(seconds) || 0));
  const s = v % 60, m = Math.floor(v / 60) % 60, h = Math.floor(v / 3600);
  return h > 0 ? `${h}:${pad2(m)}:${pad2(s)}` : `${pad2(m)}:${pad2(s)}`;
}

/** Spelled-out duration under a timer, e.g. "20 min" or "10 min, 30 sec". */
export function durationLabel(seconds) {
  const v = Math.max(0, Math.round(Number(seconds) || 0));
  const h = Math.floor(v / 3600), m = Math.floor(v / 60) % 60, s = v % 60;
  const parts = [];
  if (h) parts.push(`${h} hr`);
  if (m) parts.push(`${m} min`);
  if (s) parts.push(`${s} sec`);
  return parts.length ? parts.join(', ') : '0 sec';
}

/** Split a duration into the hr / min / sec picker columns. */
export function splitDuration(seconds) {
  const v = Math.max(0, Math.round(Number(seconds) || 0));
  return { h: Math.floor(v / 3600), m: Math.floor(v / 60) % 60, s: v % 60 };
}

/**
 * Indices of the fastest and slowest completed laps, or nulls while fewer than
 * two laps exist. `laps` holds split durations in completion order.
 */
export function lapExtrema(laps) {
  if (!Array.isArray(laps) || laps.length < 2) return { fastest: null, slowest: null };
  let fastest = 0, slowest = 0;
  for (let i = 1; i < laps.length; i++) {
    if (laps[i] < laps[fastest]) fastest = i;
    if (laps[i] > laps[slowest]) slowest = i;
  }
  return { fastest, slowest };
}

/** Minutes east of UTC for `timeZone` at `date` (DST aware, via Intl). */
export function tzOffsetMinutes(timeZone, date = new Date()) {
  try {
    const parts = new Intl.DateTimeFormat('en-US', {
      timeZone, hourCycle: 'h23', year: 'numeric', month: 'numeric', day: 'numeric',
      hour: 'numeric', minute: 'numeric', second: 'numeric',
    }).formatToParts(date);
    const get = t => Number(parts.find(p => p.type === t)?.value);
    const asUtc = Date.UTC(get('year'), get('month') - 1, get('day'), get('hour') % 24, get('minute'), get('second'));
    return Math.round((asUtc - Math.floor(date.getTime() / 1000) * 1000) / 60000);
  } catch (_) {
    return -date.getTimezoneOffset();
  }
}

/** Calendar date (y, m, d) as seen in `timeZone`. */
export function zonedYMD(timeZone, date = new Date()) {
  const shifted = new Date(date.getTime() + tzOffsetMinutes(timeZone, date) * 60000);
  return { y: shifted.getUTCFullYear(), m: shifted.getUTCMonth(), d: shifted.getUTCDate() };
}

/** Wall-clock hour/minute/second in `timeZone`. */
export function zonedClock(timeZone, date = new Date()) {
  const shifted = new Date(date.getTime() + tzOffsetMinutes(timeZone, date) * 60000);
  return {
    h: shifted.getUTCHours(), m: shifted.getUTCMinutes(),
    s: shifted.getUTCSeconds() + shifted.getUTCMilliseconds() / 1000,
  };
}

/** "Today" / "Tomorrow" / "Yesterday" for a zone relative to the local day. */
export function relativeDay(timeZone, date = new Date(), localZone) {
  const a = zonedYMD(timeZone, date);
  const b = localZone ? zonedYMD(localZone, date)
    : { y: date.getFullYear(), m: date.getMonth(), d: date.getDate() };
  const diff = Math.round((Date.UTC(a.y, a.m, a.d) - Date.UTC(b.y, b.m, b.d)) / DAY_MS);
  return diff === 0 ? 'Today' : diff > 0 ? 'Tomorrow' : 'Yesterday';
}

/** Offset label relative to local time: "+0 HRS", "-3 HRS", "+5:30 HRS", "+1 HR". */
export function offsetLabel(timeZone, date = new Date(), localOffsetMinutes) {
  const local = Number.isFinite(localOffsetMinutes) ? localOffsetMinutes : -date.getTimezoneOffset();
  const diff = tzOffsetMinutes(timeZone, date) - local;
  const sign = diff < 0 ? '-' : '+';
  const abs = Math.abs(diff);
  const h = Math.floor(abs / 60), m = abs % 60;
  const body = m ? `${h}:${pad2(m)}` : String(h);
  return `${sign}${body} ${abs === 60 ? 'HR' : 'HRS'}`;
}

/** Localised short time ("5:54 PM") for a zone. */
export function formatZoneTime(timeZone, date = new Date(), locale) {
  try {
    return new Intl.DateTimeFormat(locale, { timeZone, hour: 'numeric', minute: '2-digit' }).format(date);
  } catch (_) {
    return new Intl.DateTimeFormat(locale, { hour: 'numeric', minute: '2-digit' }).format(date);
  }
}

/** Whether the user's locale shows a 12-hour clock with AM/PM. */
export function uses12Hour(locale) {
  try {
    const opts = new Intl.DateTimeFormat(locale, { hour: 'numeric' }).resolvedOptions();
    return opts.hour12 !== false && opts.hourCycle !== 'h23' && opts.hourCycle !== 'h24';
  } catch (_) {
    return true;
  }
}

/** Alarm clock face text: { time: "7:05", period: "AM" } (period empty for 24h). */
export function alarmTimeParts(hour, minute, twelveHour = true) {
  if (!twelveHour) return { time: `${pad2(hour)}:${pad2(minute)}`, period: '' };
  const h12 = hour % 12 === 0 ? 12 : hour % 12;
  return { time: `${h12}:${pad2(minute)}`, period: hour < 12 ? 'AM' : 'PM' };
}

/** Repeat summary the way Clock words it. `days` holds 0 (Sun) … 6 (Sat). */
export function repeatSummary(days) {
  const set = [...new Set((days || []).filter(d => d >= 0 && d <= 6))].sort((a, b) => a - b);
  if (!set.length) return '';
  if (set.length === 7) return 'every day';
  if (set.join() === '1,2,3,4,5') return 'weekdays';
  if (set.join() === '0,6') return 'weekends';
  if (set.length === 1) return `every ${['Sunday', 'Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday'][set[0]]}`;
  return set.map(d => WEEKDAY_SHORT[d]).join(' ');
}

/** Second line under an alarm: "Alarm, weekdays" (ALARM_DETAIL_FORMAT). */
export function alarmDetail(alarm) {
  const label = (alarm?.label || '').trim() || 'Alarm';
  const repeat = repeatSummary(alarm?.days);
  return repeat ? `${label}, ${repeat}` : label;
}

/**
 * Next time an alarm rings at or after `from` (local time). One-off alarms ring
 * at the next matching minute; repeating alarms on their next selected day.
 */
export function nextAlarmDate(alarm, from = new Date()) {
  const days = alarm?.days || [];
  for (let add = 0; add <= 7; add++) {
    const c = new Date(from.getFullYear(), from.getMonth(), from.getDate() + add, alarm.hour, alarm.minute, 0, 0);
    if (c.getTime() <= from.getTime()) continue;
    if (!days.length || days.includes(c.getDay())) return c;
  }
  return null;
}

// ── Sun position (NOAA approximations) ───────────────────────────────────

const rad = d => d * Math.PI / 180;
const deg = r => r * 180 / Math.PI;

function solarParams(date) {
  const jd = date.getTime() / DAY_MS + 2440587.5;
  const t = (jd - 2451545) / 36525;
  const l0 = (280.46646 + t * (36000.76983 + t * 0.0003032)) % 360;
  const m = 357.52911 + t * (35999.05029 - 0.0001537 * t);
  const e = 0.016708634 - t * (0.000042037 + 0.0000001267 * t);
  const c = Math.sin(rad(m)) * (1.914602 - t * (0.004817 + 0.000014 * t))
    + Math.sin(rad(2 * m)) * (0.019993 - 0.000101 * t) + Math.sin(rad(3 * m)) * 0.000289;
  const lambda = l0 + c - 0.00569 - 0.00478 * Math.sin(rad(125.04 - 1934.136 * t));
  const eps0 = 23 + (26 + (21.448 - t * (46.815 + t * (0.00059 - t * 0.001813))) / 60) / 60;
  const eps = eps0 + 0.00256 * Math.cos(rad(125.04 - 1934.136 * t));
  const decl = deg(Math.asin(Math.sin(rad(eps)) * Math.sin(rad(lambda))));
  const y = Math.tan(rad(eps / 2)) ** 2;
  const eqTime = 4 * deg(y * Math.sin(2 * rad(l0)) - 2 * e * Math.sin(rad(m))
    + 4 * e * y * Math.sin(rad(m)) * Math.cos(2 * rad(l0))
    - 0.5 * y * y * Math.sin(4 * rad(l0)) - 1.25 * e * e * Math.sin(2 * rad(m)));
  return { decl, eqTime };
}

/** Latitude/longitude where the sun is overhead at `date`. */
export function subsolarPoint(date = new Date()) {
  const { decl, eqTime } = solarParams(date);
  const minutes = date.getUTCHours() * 60 + date.getUTCMinutes() + date.getUTCSeconds() / 60;
  let lon = -(minutes + eqTime - 720) / 4;
  lon = ((lon + 540) % 360) - 180;
  return { lat: decl, lon };
}

/**
 * Day/night terminator as [lon, lat] points from -180 to 180, plus which pole
 * is dark, so a caller can close the night polygon.
 */
export function terminator(date = new Date(), step = 2) {
  const { lat: dec, lon: sunLon } = subsolarPoint(date);
  const d = Math.abs(dec) < 0.01 ? 0.01 : dec;
  const pts = [];
  for (let lon = -180; lon <= 180; lon += step) {
    const lat = deg(Math.atan(-Math.cos(rad(lon - sunLon)) / Math.tan(rad(d))));
    pts.push([lon, lat]);
  }
  return { points: pts, darkPole: d > 0 ? 'south' : 'north' };
}

/** Whether the sun is up at a place (for day/night clock faces). */
export function isDaylight(lat, lon, date = new Date()) {
  const { lat: dec, lon: sunLon } = subsolarPoint(date);
  const cosZ = Math.sin(rad(lat)) * Math.sin(rad(dec))
    + Math.cos(rad(lat)) * Math.cos(rad(dec)) * Math.cos(rad(lon - sunLon));
  return cosZ > Math.cos(rad(90.833));
}

/**
 * Sunrise and sunset (as Dates) for the civil day in `timeZone` containing
 * `date`. Either is null during polar day/night.
 */
export function sunTimes(lat, lon, timeZone, date = new Date()) {
  const { y, m, d } = zonedYMD(timeZone, date);
  const noonUtc = new Date(Date.UTC(y, m, d, 12));
  const { decl, eqTime } = solarParams(noonUtc);
  const cosH = (Math.cos(rad(90.833)) - Math.sin(rad(lat)) * Math.sin(rad(decl)))
    / (Math.cos(rad(lat)) * Math.cos(rad(decl)));
  if (cosH > 1 || cosH < -1) return { sunrise: null, sunset: null };
  const ha = deg(Math.acos(cosH));
  const at = minutesUtc => new Date(Date.UTC(y, m, d) + minutesUtc * 60000);
  return {
    sunrise: at(720 - 4 * (lon + ha) - eqTime),
    sunset: at(720 - 4 * (lon - ha) - eqTime),
  };
}
