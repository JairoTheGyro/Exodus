/**
 * Calculator — unit-picker data and the currency-rate client.
 *
 * The unit table and all conversion maths live in the Rust engine
 * (`native/calculator/src/units.rs`); the window gets the table once through
 * `core.units()`. This file adds what needs the browser: currency names from
 * `Intl`, and rates from Exodus's own `/api/calculator/rates` route, which is
 * only asked when the Currency category is used.
 */

let currencyNames = null;
function currencyName(code) {
  try {
    currencyNames ??= new Intl.DisplayNames(['en'], { type: 'currency' });
    return currencyNames.of(code) || code;
  } catch (_) {
    return code;
  }
}

/** Picker rows for the current rates (rates are units per US dollar). */
export function currencyUnits(rates) {
  if (!rates) return [];
  return Object.entries(rates.rates)
    .filter(([, perUsd]) => perUsd > 0)
    .map(([code]) => ({ id: `currency.${code}`, category: 'Currency', name: currencyName(code), abbr: code }))
    .sort((a, b) => a.name.localeCompare(b.name));
}

/** `catalog` is `core.units()`: { categories, units }. */
export function unitsIn(category, catalog, rates) {
  return category === 'Currency' ? currencyUnits(rates) : catalog.units.filter(x => x.category === category);
}

export function findUnit(id, catalog, rates) {
  if (!id) return null;
  if (id.startsWith('currency.')) return currencyUnits(rates).find(x => x.id === id) || null;
  return catalog.units.find(x => x.id === id) || null;
}

// ── Currency rates (same-origin) ────────────────────────────────────────

const RATES_KEY = 'odysseus-calculator-rates-v1';
let ratesCache = null;
let pending = null;

export function cachedRates() {
  if (ratesCache) return ratesCache;
  try {
    const saved = JSON.parse(localStorage.getItem(RATES_KEY) || 'null');
    if (saved && saved.rates && typeof saved.updated === 'number') ratesCache = saved;
  } catch (_) {}
  return ratesCache;
}

/**
 * Asks Exodus for fresh rates (the server fetches ExchangeRate-API and caches
 * it). Resolves to the rates, or to the last cached copy / null when offline.
 */
export function refreshRates({ force = false } = {}) {
  const have = cachedRates();
  if (!force && have && Date.now() / 1000 - have.fetchedAt < 6 * 3600) return Promise.resolve(have);
  pending ??= fetch('/api/calculator/rates', { credentials: 'same-origin', headers: { Accept: 'application/json' } })
    .then(r => (r.ok ? r.json() : null))
    .then(data => {
      if (data && data.rates && typeof data.updated === 'number') {
        ratesCache = { rates: data.rates, updated: data.updated, source: data.source, stale: !!data.stale, fetchedAt: Date.now() / 1000 };
        try { localStorage.setItem(RATES_KEY, JSON.stringify(ratesCache)); } catch (_) {}
      }
      return cachedRates();
    })
    .catch(() => cachedRates())
    .finally(() => { pending = null; });
  return pending;
}
