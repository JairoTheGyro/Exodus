/**
 * Calculator — unit catalog for Convert mode and the currency-rate client.
 *
 * Each unit converts through its category's base unit:
 * base = value × factor + offset (temperature), or factor ÷ value for the
 * reciprocal fuel-economy units. Currency rates come from Exodus's own
 * `/api/calculator/rates` route and are only requested when Currency is used.
 */

import { Dec } from './decimal.js';

export const CATEGORIES = [
  'Angle', 'Area', 'Currency', 'Data', 'Energy', 'Force', 'Fuel', 'Length',
  'Power', 'Pressure', 'Speed', 'Temperature', 'Time', 'Volume', 'Weight',
];

const u = (category, key, name, abbr, factor, offset = 0, reciprocal = false) =>
  ({ id: `${category.toLowerCase()}.${key}`, category, name, abbr, factor, offset, reciprocal });

/** Bases: degree, m², byte, joule, newton, L/100 km, metre, watt, pascal, m/s, kelvin, second, litre, kilogram. */
export const UNITS = [
  u('Angle', 'deg', 'Degrees', 'deg', 1),
  u('Angle', 'rad', 'Radians', 'rad', 180 / Math.PI),
  u('Angle', 'grad', 'Gradians', 'grad', 0.9),
  u('Angle', 'rev', 'Revolutions', 'rev', 360),
  u('Angle', 'arcmin', 'Arc Minutes', 'arcmin', 1 / 60),
  u('Angle', 'arcsec', 'Arc Seconds', 'arcsec', 1 / 3600),
  u('Area', 'km2', 'Square Kilometers', 'km²', 1e6),
  u('Area', 'ha', 'Hectares', 'ha', 1e4),
  u('Area', 'm2', 'Square Meters', 'm²', 1),
  u('Area', 'cm2', 'Square Centimeters', 'cm²', 1e-4),
  u('Area', 'mm2', 'Square Millimeters', 'mm²', 1e-6),
  u('Area', 'mi2', 'Square Miles', 'mi²', 2589988.110336),
  u('Area', 'ac', 'Acres', 'ac', 4046.8564224),
  u('Area', 'yd2', 'Square Yards', 'yd²', 0.83612736),
  u('Area', 'ft2', 'Square Feet', 'ft²', 0.09290304),
  u('Area', 'in2', 'Square Inches', 'in²', 0.00064516),
  u('Data', 'bit', 'Bits', 'bit', 0.125),
  u('Data', 'B', 'Bytes', 'B', 1),
  u('Data', 'kbit', 'Kilobits', 'kbit', 125),
  u('Data', 'KB', 'Kilobytes', 'KB', 1e3),
  u('Data', 'KiB', 'Kibibytes', 'KiB', 1024),
  u('Data', 'Mbit', 'Megabits', 'Mbit', 125000),
  u('Data', 'MB', 'Megabytes', 'MB', 1e6),
  u('Data', 'MiB', 'Mebibytes', 'MiB', 1048576),
  u('Data', 'Gbit', 'Gigabits', 'Gbit', 1.25e8),
  u('Data', 'GB', 'Gigabytes', 'GB', 1e9),
  u('Data', 'GiB', 'Gibibytes', 'GiB', 1073741824),
  u('Data', 'TB', 'Terabytes', 'TB', 1e12),
  u('Data', 'TiB', 'Tebibytes', 'TiB', 1099511627776),
  u('Data', 'PB', 'Petabytes', 'PB', 1e15),
  u('Energy', 'J', 'Joules', 'J', 1),
  u('Energy', 'kJ', 'Kilojoules', 'kJ', 1e3),
  u('Energy', 'cal', 'Calories', 'cal', 4.184),
  u('Energy', 'kcal', 'Kilocalories', 'kcal', 4184),
  u('Energy', 'Wh', 'Watt-Hours', 'Wh', 3600),
  u('Energy', 'kWh', 'Kilowatt-Hours', 'kWh', 3.6e6),
  u('Energy', 'BTU', 'British Thermal Units', 'BTU', 1055.05585262),
  u('Energy', 'eV', 'Electronvolts', 'eV', 1.602176634e-19),
  u('Force', 'N', 'Newtons', 'N', 1),
  u('Force', 'kN', 'Kilonewtons', 'kN', 1e3),
  u('Force', 'dyn', 'Dynes', 'dyn', 1e-5),
  u('Force', 'lbf', 'Pound-Force', 'lbf', 4.4482216152605),
  u('Force', 'kgf', 'Kilogram-Force', 'kgf', 9.80665),
  u('Fuel', 'l100km', 'Liters per 100 Kilometers', 'L/100km', 1),
  u('Fuel', 'kml', 'Kilometers per Liter', 'km/L', 100, 0, true),
  u('Fuel', 'mpg', 'Miles per Gallon', 'mpg', 235.214583, 0, true),
  u('Fuel', 'mpgimp', 'Miles per Imperial Gallon', 'mpg (imp)', 282.480936, 0, true),
  u('Length', 'km', 'Kilometers', 'km', 1e3),
  u('Length', 'm', 'Meters', 'm', 1),
  u('Length', 'cm', 'Centimeters', 'cm', 1e-2),
  u('Length', 'mm', 'Millimeters', 'mm', 1e-3),
  u('Length', 'um', 'Micrometers', 'µm', 1e-6),
  u('Length', 'nm', 'Nanometers', 'nm', 1e-9),
  u('Length', 'mi', 'Miles', 'mi', 1609.344),
  u('Length', 'yd', 'Yards', 'yd', 0.9144),
  u('Length', 'ft', 'Feet', 'ft', 0.3048),
  u('Length', 'in', 'Inches', 'in', 0.0254),
  u('Length', 'nmi', 'Nautical Miles', 'NM', 1852),
  u('Length', 'ly', 'Light-Years', 'ly', 9.4607304725808e15),
  u('Power', 'mW', 'Milliwatts', 'mW', 1e-3),
  u('Power', 'W', 'Watts', 'W', 1),
  u('Power', 'kW', 'Kilowatts', 'kW', 1e3),
  u('Power', 'MW', 'Megawatts', 'MW', 1e6),
  u('Power', 'hp', 'Horsepower', 'hp', 745.69987158227),
  u('Pressure', 'Pa', 'Pascals', 'Pa', 1),
  u('Pressure', 'hPa', 'Hectopascals', 'hPa', 100),
  u('Pressure', 'kPa', 'Kilopascals', 'kPa', 1e3),
  u('Pressure', 'bar', 'Bars', 'bar', 1e5),
  u('Pressure', 'mbar', 'Millibars', 'mbar', 100),
  u('Pressure', 'atm', 'Atmospheres', 'atm', 101325),
  u('Pressure', 'psi', 'Pounds per Square Inch', 'psi', 6894.757293168),
  u('Pressure', 'inHg', 'Inches of Mercury', 'inHg', 3386.389),
  u('Pressure', 'mmHg', 'Millimeters of Mercury', 'mmHg', 133.322387415),
  u('Speed', 'mps', 'Meters per Second', 'm/s', 1),
  u('Speed', 'kmh', 'Kilometers per Hour', 'km/h', 1 / 3.6),
  u('Speed', 'mph', 'Miles per Hour', 'mph', 0.44704),
  u('Speed', 'fps', 'Feet per Second', 'ft/s', 0.3048),
  u('Speed', 'kn', 'Knots', 'kn', 1852 / 3600),
  u('Temperature', 'C', 'Celsius', '°C', 1, 273.15),
  u('Temperature', 'F', 'Fahrenheit', '°F', 5 / 9, 273.15 - 32 * 5 / 9),
  u('Temperature', 'K', 'Kelvin', 'K', 1),
  u('Time', 'ns', 'Nanoseconds', 'ns', 1e-9),
  u('Time', 'us', 'Microseconds', 'µs', 1e-6),
  u('Time', 'ms', 'Milliseconds', 'ms', 1e-3),
  u('Time', 's', 'Seconds', 's', 1),
  u('Time', 'min', 'Minutes', 'min', 60),
  u('Time', 'h', 'Hours', 'h', 3600),
  u('Time', 'd', 'Days', 'd', 86400),
  u('Time', 'wk', 'Weeks', 'wk', 604800),
  u('Time', 'yr', 'Years', 'yr', 31557600),
  u('Volume', 'm3', 'Cubic Meters', 'm³', 1e3),
  u('Volume', 'L', 'Liters', 'L', 1),
  u('Volume', 'mL', 'Milliliters', 'mL', 1e-3),
  u('Volume', 'cm3', 'Cubic Centimeters', 'cm³', 1e-3),
  u('Volume', 'gal', 'Gallons', 'gal', 3.785411784),
  u('Volume', 'galimp', 'Imperial Gallons', 'gal (imp)', 4.54609),
  u('Volume', 'qt', 'Quarts', 'qt', 0.946352946),
  u('Volume', 'pt', 'Pints', 'pt', 0.473176473),
  u('Volume', 'cup', 'Cups', 'cup', 0.2365882365),
  u('Volume', 'floz', 'Fluid Ounces', 'fl oz', 0.0295735295625),
  u('Volume', 'tbsp', 'Tablespoons', 'tbsp', 0.01478676478125),
  u('Volume', 'tsp', 'Teaspoons', 'tsp', 0.00492892159375),
  u('Volume', 'ft3', 'Cubic Feet', 'ft³', 28.316846592),
  u('Volume', 'in3', 'Cubic Inches', 'in³', 0.016387064),
  u('Weight', 't', 'Metric Tons', 't', 1e3),
  u('Weight', 'kg', 'Kilograms', 'kg', 1),
  u('Weight', 'g', 'Grams', 'g', 1e-3),
  u('Weight', 'mg', 'Milligrams', 'mg', 1e-6),
  u('Weight', 'lb', 'Pounds', 'lb', 0.45359237),
  u('Weight', 'oz', 'Ounces', 'oz', 0.028349523125),
  u('Weight', 'st', 'Stones', 'st', 6.35029318),
  u('Weight', 'ton', 'Short Tons', 'ton', 907.18474),
];

const toBase = (unit, v) => unit.reciprocal ? (v === 0 ? Infinity : unit.factor / v) : v * unit.factor + unit.offset;
const fromBase = (unit, v) => unit.reciprocal ? (v === 0 ? Infinity : unit.factor / v) : (v - unit.offset) / unit.factor;

/** Converts a Dec between two units of one category; null when impossible. */
export function convert(value, from, to) {
  if (!from || !to || from.category !== to.category) return null;
  if (from.id === to.id) return value;
  const out = fromBase(to, toBase(from, Dec.from(value).toNumber()));
  return Number.isFinite(out) ? Dec.fromNumber(out) : null;
}

let currencyNames = null;
function currencyName(code) {
  try {
    currencyNames ??= new Intl.DisplayNames(['en'], { type: 'currency' });
    return currencyNames.of(code) || code;
  } catch (_) {
    return code;
  }
}

/** Units for the current rates (rates are units per US dollar). */
export function currencyUnits(rates) {
  if (!rates) return [];
  return Object.entries(rates.rates)
    .filter(([, perUsd]) => perUsd > 0)
    .map(([code, perUsd]) => ({ id: `currency.${code}`, category: 'Currency', name: currencyName(code), abbr: code, factor: 1 / perUsd, offset: 0, reciprocal: false }))
    .sort((a, b) => a.name.localeCompare(b.name));
}

export function unitsIn(category, rates) {
  return category === 'Currency' ? currencyUnits(rates) : UNITS.filter(x => x.category === category);
}

export function findUnit(id, rates) {
  if (!id) return null;
  if (id.startsWith('currency.')) return currencyUnits(rates).find(x => x.id === id) || null;
  return UNITS.find(x => x.id === id) || null;
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
