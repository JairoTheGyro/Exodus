/**
 * Calculator — a recreation of the macOS Calculator app as an Exodus tool
 * window: Basic, Scientific and Programmer modes, RPN, unit conversion and a
 * history sidebar.
 *
 * Loaded lazily through panels.js (`loadPanel('calculator')`). The window uses
 * the shared tool-window plumbing (modalManager for minimize/dock/restore,
 * windowDrag for moving) and only theme tokens for colour, so it follows
 * whichever Exodus theme is active. All state lives in this browser
 * (`odysseus-calculator-v1`); the only network use is Convert → Currency,
 * which asks Exodus's own /api/calculator/rates route.
 */

import * as Modals from '../modalManager.js';
import { makeWindowDraggable } from '../windowDrag.js';
import { topPortalZ } from '../toolWindowZOrder.js';
import { bindMenuDismiss } from '../escMenuStack.js';
import { Dec, PI, E } from './decimal.js';
import { AlgebraicCalculator, RPNCalculator, NumberFormat, render, plainText, integerString } from './engine.js';
import { CATEGORIES, UNITS, convert, unitsIn, findUnit, currencyUnits, cachedRates, refreshRates } from './units.js';

const MODAL_ID = 'calculator-modal';
const SIDEBAR_BTN_ID = 'tool-calculator-btn';
const RAIL_BTN_ID = 'rail-calculator';
const DOCK_ICON = 'M7 2h10a2 2 0 0 1 2 2v16a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2zM8 5h8v4H8zM8.5 13h.01M12 13h.01M15.5 13h.01M8.5 17h.01M12 17h.01M15.5 17h.01';
const STORE_KEY = 'odysseus-calculator-v1';
const CSS_HREF = '/static/js/calculator/calculator.css';
const MAX_HISTORY = 100;

// ── Small DOM helpers ───────────────────────────────────────────────────

function h(spec, props = {}, ...children) {
  const m = /^([a-z0-9-]+)?((?:[.#][\w-]+)*)$/i.exec(spec) || [];
  const el = document.createElement(m[1] || 'div');
  (m[2] || '').replace(/([.#])([\w-]+)/g, (_, kind, name) => {
    if (kind === '.') el.classList.add(name); else el.id = name;
    return '';
  });
  for (const [k, v] of Object.entries(props || {})) {
    if (v == null || v === false) continue;
    if (k === 'on') for (const [ev, fn] of Object.entries(v)) el.addEventListener(ev, fn);
    else if (k === 'text') el.textContent = v;
    else if (k === 'html') el.innerHTML = v;
    else if (k === 'dataset') Object.assign(el.dataset, v);
    else if (k in el && typeof v !== 'string') el[k] = v;
    else el.setAttribute(k, v === true ? '' : v);
  }
  for (const c of children.flat()) {
    if (c == null || c === false) continue;
    el.append(c instanceof Node ? c : document.createTextNode(String(c)));
  }
  return el;
}

const svg = (body, size = 16, sw = 2) =>
  `<svg width="${size}" height="${size}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="${sw}" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${body}</svg>`;

const ICONS = {
  calculator: svg('<rect x="5" y="2" width="14" height="20" rx="2"/><rect x="8" y="5" width="8" height="4" rx=".5"/><path d="M8.5 13h.01M12 13h.01M15.5 13h.01M8.5 17h.01M12 17h.01M15.5 17h.01"/>', 14),
  calculatorBig: svg('<rect x="5" y="2" width="14" height="20" rx="2"/><rect x="8" y="5" width="8" height="4" rx=".5"/><path d="M8.5 13h.01M12 13h.01M15.5 13h.01M8.5 17h.01M12 17h.01M15.5 17h.01"/>', 16),
  sidebar: svg('<rect x="3" y="4" width="18" height="16" rx="2"/><path d="M9 4v16M5.5 8h1.5M5.5 11h1.5M5.5 14h1.5"/>', 16),
  backspace: svg('<path d="M21 5H9l-6 7 6 7h12a1 1 0 0 0 1-1V6a1 1 0 0 0-1-1z"/><path d="m12 9 6 6M18 9l-6 6"/>', 22, 1.6),
  divide: svg('<path d="M5 12h14"/><circle cx="12" cy="6.5" r="1.1" fill="currentColor"/><circle cx="12" cy="17.5" r="1.1" fill="currentColor"/>', 24, 1.7),
  multiply: svg('<path d="m6.5 6.5 11 11M17.5 6.5l-11 11"/>', 24, 1.7),
  minus: svg('<path d="M5 12h14"/>', 24, 1.7),
  plus: svg('<path d="M12 5v14M5 12h14"/>', 24, 1.7),
  equal: svg('<path d="M5 9h14M5 15h14"/>', 24, 1.7),
  swap: svg('<path d="M7 4v16M3 8l4-4 4 4M17 20V4M13 16l4 4 4-4"/>', 16, 1.8),
  chevrons: '<svg width="7" height="9" viewBox="0 0 7 9" aria-hidden="true"><path d="M1 3.2 3.5 1 6 3.2M1 5.8 3.5 8 6 5.8" fill="none" stroke="currentColor" stroke-width="1.3" stroke-linecap="round" stroke-linejoin="round"/></svg>',
  basic: svg('<path d="M4 7h6M7 4v6M14 7h6M4 17h6M15 15l4 4M19 15l-4 4"/>', 14),
  scientific: svg('<path d="M9 20c2 0 2.5-1.5 3-4l1.5-8c.5-2.5 1-4 3-4M8 10h8"/>', 14),
  programmer: svg('<rect x="7" y="7" width="10" height="10" rx="1"/><path d="M10 3v4M14 3v4M10 17v4M14 17v4M3 10h4M3 14h4M17 10h4M17 14h4"/>', 14),
  notes: svg('<path d="M4 6h7M7.5 2.5v7M14 18h6M4 15l5 5M9 15l-5 5M15 5l5 5"/>', 14),
};

/** Display spans → nested <sup>/<sub> markup. */
function spansToNodes(spans) {
  const frag = document.createDocumentFragment();
  for (const s of spans) {
    let node = s.italic ? h('span.calc-italic', { text: s.text }) : document.createTextNode(s.text);
    for (let l = s.level; l > 0; l--) node = h('sup.calc-sup', {}, node);
    for (let l = s.level; l < 0; l++) node = h('sub.calc-sub', {}, node);
    frag.append(node);
  }
  return frag;
}

/** Compact label notation: `x^2` → x², `log_10` → log₁₀, `|` returns to baseline. */
function label(text) {
  const spans = [];
  let level = 0;
  let buf = '';
  const flush = () => { if (buf) spans.push({ text: buf, level, italic: false }); buf = ''; };
  for (const ch of text) {
    if (ch === '^') { flush(); level = 1; }
    else if (ch === '_') { flush(); level = -1; }
    else if (ch === '|') { flush(); level = 0; }
    else if (ch === '𝑒') { flush(); spans.push({ text: 'e', level, italic: true }); }
    else buf += ch;
  }
  flush();
  return spans;
}

// ── Saved state ─────────────────────────────────────────────────────────

const DEFAULTS = {
  mode: 'basic', rpn: false, convert: false, showHistory: false,
  thousands: true, places: null, angle: 'deg', base: 16, showBinary: true, charView: 'none',
  inUnit: 'length.m', outUnit: 'length.ft', recentUnits: [], history: [],
};

function loadState() {
  try {
    const saved = JSON.parse(localStorage.getItem(STORE_KEY) || 'null');
    return { ...DEFAULTS, ...(saved && typeof saved === 'object' ? saved : {}) };
  } catch (_) {
    return { ...DEFAULTS };
  }
}

let state = loadState();

function save() {
  try { localStorage.setItem(STORE_KEY, JSON.stringify(state)); } catch (_) {}
}

// ── Model ───────────────────────────────────────────────────────────────

const algebraic = new AlgebraicCalculator('decimal');
const programmer = new AlgebraicCalculator('programmer');
const rpnCalc = new RPNCalculator();
let memory = null;          // Dec | null (not persisted, like Calculator.app)
let second = false;
let shiftHeld = false;
let rates = cachedRates();
let ratesLoading = false;

algebraic.angle = rpnCalc.angle = state.angle;
programmer.base = state.base;

const rpnActive = () => state.rpn && state.mode !== 'programmer';
const historyAvailable = () => state.mode !== 'programmer' && !rpnActive();
const showsSecond = () => second !== shiftHeld;
const active = () => (state.mode === 'programmer' ? programmer : algebraic);
const format = () => new NumberFormat({ grouping: state.thousands, places: state.places });

function displayedValue() {
  if (rpnActive()) return rpnCalc.x;
  return active().currentValue;
}

function clearLabel() {
  if (rpnActive()) return rpnCalc.showsAllClear ? 'AC' : 'C';
  return active().showsAllClear ? 'AC' : 'C';
}

function record(tokens, value) {
  const spans = render(tokens, format(), { showsBase: state.mode === 'programmer' });
  state.history.unshift({
    id: `${Date.now().toString(36)}${Math.random().toString(36).slice(2, 6)}`,
    at: Date.now(), expr: spans, result: value.toPlain(), mode: state.mode, base: active().base,
  });
  if (state.history.length > MAX_HISTORY) state.history.length = MAX_HISTORY;
  save();
}

function press(key) {
  const [kind, arg] = key;
  if (kind === 'second') { second = !second; return; }
  if (kind === 'angle') { setAngle(state.angle === 'deg' ? 'rad' : 'deg'); return; }
  if (kind === 'mc') { memory = null; return; }
  if (kind === 'm+' || kind === 'm-') {
    const v = displayedValue();
    if (v) memory = (memory || new Dec(0n))[kind === 'm+' ? 'add' : 'sub'](v);
    return;
  }
  if (rpnActive()) { pressRPN(kind, arg); return; }
  const c = active();
  if (state.mode === 'programmer') c.base = state.base;
  switch (kind) {
    case 'digit':
      if (arg === 'FF') { c.inputDigit('F'); c.inputDigit('F'); } else c.inputDigit(arg);
      break;
    case '00': c.inputDigit('0'); c.inputDigit('0'); break;
    case 'point': c.inputPoint(); break;
    case 'op': c.inputOperator(arg); break;
    case 'equals': { const r = c.equals(); if (r) record(r.tokens, r.value); break; }
    case 'post': c.applyPostfix(arg); break;
    case 'fn': c.applyFunction(arg); break;
    case 'sign': c.toggleSign(); break;
    case 'back': c.backspace(); break;
    case 'clear': c.clear(); break;
    case 'clearAll': c.clearAll(); break;
    case 'open': c.openParen(); break;
    case 'close': c.closeParen(); break;
    case 'pi': c.inputConstant('pi'); break;
    case 'e': c.inputConstant('e'); break;
    case 'rand': c.inputConstant(Dec.fromNumber(Math.random())); break;
    case 'mr': if (memory) c.inputValue(memory); break;
    case 'shl1': c.shiftByOne(true); break;
    case 'shr1': c.shiftByOne(false); break;
    default: break;
  }
}

function pressRPN(kind, arg) {
  const r = rpnCalc;
  switch (kind) {
    case 'digit': r.inputDigit(arg); break;
    case '00': r.inputDigit('0'); r.inputDigit('0'); break;
    case 'point': r.inputPoint(); break;
    case 'op': r.binary(arg); break;
    case 'equals': r.enter(); break;
    case 'post': r.postfix(arg); break;
    case 'fn': r.unary(arg); break;
    case 'sign': r.toggleSign(); break;
    case 'back': r.backspace(); break;
    case 'clear': case 'clearAll': r.clear(); break;
    case 'pi': r.push(PI); break;
    case 'e': r.push(E); break;
    case 'rand': r.push(Dec.fromNumber(Math.random())); break;
    case 'mr': if (memory) r.push(memory); break;
    case 'swap': r.swap(); break;
    case 'rdown': r.rollDown(); break;
    case 'rup': r.rollUp(); break;
    case 'drop': r.drop(); break;
    default: break;
  }
}

function setAngle(angle) {
  state.angle = angle;
  algebraic.angle = rpnCalc.angle = angle;
  save();
}

function setMode(mode) {
  if (mode === state.mode) return;
  const old = state.mode;
  second = false;
  // Carry the displayed value across decimal ↔ programmer.
  if (mode === 'programmer' && old !== 'programmer') {
    const v = algebraic.currentValue;
    programmer.clearAll();
    programmer.base = state.base;
    if (v && !v.isZero) programmer.inputValue(v);
  } else if (old === 'programmer' && mode !== 'programmer') {
    const v = programmer.currentValue;
    algebraic.clearAll();
    if (v && !v.isZero) algebraic.inputValue(v);
  }
  state.mode = mode;
  save();
}

function setBase(base) {
  state.base = base;
  programmer.convertBase(base);
  save();
}

function toggleConvert() {
  if (state.mode === 'programmer') return;
  state.convert = !state.convert;
  if (state.convert) state.rpn = false;
  save();
}

function toggleRPN() {
  if (state.mode === 'programmer') return;
  state.rpn = !state.rpn;
  if (state.rpn) state.convert = false;
  save();
}

function currentInt() {
  return programmer.currentOperandInt;
}

// ── Keypads (layouts measured from Calculator 12.0) ─────────────────────

const K = (key, text, style = 'digit', help = '', extra = {}) => ({ key, text, style, help, ...extra });
const OPS = () => [
  K(['op', 'div'], { icon: 'divide' }, 'op', 'Divide (or press /)'),
  K(['op', 'mul'], { icon: 'multiply' }, 'op', 'Multiply (or press *)'),
  K(['op', 'sub'], { icon: 'minus' }, 'op', 'Subtract (or press -)'),
  K(['op', 'add'], { icon: 'plus' }, 'op', 'Add (or press +)'),
];
const equalsKey = (rpn) => rpn
  ? K(['equals'], 'enter', 'op', 'Enter the value onto the stack (or press Return)', { wide: true })
  : K(['equals'], { icon: 'equal' }, 'op', 'Equals (or press Return)');
const backKey = (style = 'util') => K(['back'], { icon: 'backspace' }, style, 'Delete the last digit or operation entered (long press to delete all)');
const clearKey = () => {
  const t = clearLabel();
  return K(['clear'], t, 'util', t === 'AC' ? 'Clear all (or press Escape)' : 'Clear (or press Escape)');
};
const digit = (d, enabled = true) => K(['digit', d], d, 'digit', d, { disabled: !enabled });
const decimalPoint = () => K(['point'], format().decimalSep, 'digit', 'Point');

function basicColumns(rpn) {
  const ops = OPS();
  return [
    [backKey(), clearKey(), K(['post', 'pct'], '%', 'util', 'Percent (or press %)'), ops[0]],
    [digit('7'), digit('8'), digit('9'), ops[1]],
    [digit('4'), digit('5'), digit('6'), ops[2]],
    [digit('1'), digit('2'), digit('3'), ops[3]],
    [K(['sign'], '⁺∕₋', 'digit', 'Change sign of a value (or press Option-Minus [-])'), digit('0'), decimalPoint(), equalsKey(rpn)],
  ];
}

function scientificColumns(rpn) {
  const s = showsSecond();
  const fn = (key, text, help, extra = {}) => K(key, text, 'fn', help, extra);
  return [
    [fn(['open'], '(', 'Open parenthesis', { disabled: rpn }), fn(['close'], ')', 'Close parenthesis', { disabled: rpn }),
      fn(['mc'], 'mc', 'Clear the memory'), fn(['m+'], 'm+', 'Add the displayed value to the memory'),
      fn(['m-'], 'm-', 'Subtract the displayed value from the memory'), fn(['mr'], 'mr', 'Recall the value stored in the memory')],
    [K(['second'], '2^nd', s ? 'fn-on' : 'fn', 'Show alternate functions for some buttons (or hold Shift)'),
      fn(['post', 'sq'], 'x^2', 'Calculate the square of a value'),
      fn(['post', 'cube'], 'x^3', 'Calculate the cube of a value'),
      fn(['op', 'pow'], rpn ? 'y^x' : 'x^y', 'Calculate a first value to the power of a second value (or press ^)'),
      s ? fn(['op', 'rpow'], 'y^x', 'Calculate a second value to the power of a first value') : fn(['fn', 'exp'], '𝑒^x', 'Calculate e to the power of a value'),
      s ? fn(['fn', 'twoPow'], '2^x', 'Calculate 2 to the power of a value') : fn(['fn', 'tenPow'], '10^x', 'Calculate 10 to the power of a value')],
    [fn(['fn', 'recip'], '^1|⁄_x', 'Calculate the reciprocal of a value'),
      fn(['fn', 'sqrt'], '^2|√x', 'Calculate the square root of a value (or press Option-V)'),
      fn(['fn', 'cbrt'], '^3|√x', 'Calculate the cube root of a value'),
      fn(['op', 'root'], rpn ? '^x|√y' : '^y|√x', rpn ? 'Calculate an arbitrary root of a value (x-th root of y)' : 'Calculate an arbitrary root of a value (y-th root of x)'),
      s ? fn(['op', 'logy'], 'log_y', 'Calculate the logarithm to an arbitrary base of a value') : fn(['fn', 'ln'], 'ln', 'Calculate the natural logarithm of a value (or press e)'),
      s ? fn(['fn', 'log2'], 'log_2', 'Calculate the logarithm to base 2 of a value') : fn(['fn', 'log10'], 'log_10', 'Calculate the logarithm to base 10 of a value')],
    [fn(['post', 'fact'], 'x!', 'Calculate the factorial of a value (or press !)'),
      s ? fn(['fn', 'asin'], 'sin^-1', 'Calculate the inverse sine of a value') : fn(['fn', 'sin'], 'sin', 'Calculate the sine of a value'),
      s ? fn(['fn', 'acos'], 'cos^-1', 'Calculate the inverse cosine of a value') : fn(['fn', 'cos'], 'cos', 'Calculate the cosine of a value'),
      s ? fn(['fn', 'atan'], 'tan^-1', 'Calculate the inverse tangent of a value') : fn(['fn', 'tan'], 'tan', 'Calculate the tangent of a value'),
      fn(['e'], '𝑒', 'Enter 𝑒 (2.71828…)'),
      fn(['op', 'ee'], 'EE', 'Enter exponent for a value (scientific notation) (or press Shift-E)')],
    [fn(['rand'], 'Rand', 'Generate a random number between 0 and 1'),
      s ? fn(['fn', 'asinh'], 'sinh^-1', 'Calculate the inverse hyperbolic sine of a value') : fn(['fn', 'sinh'], 'sinh', 'Calculate the hyperbolic sine of a value'),
      s ? fn(['fn', 'acosh'], 'cosh^-1', 'Calculate the inverse hyperbolic cosine of a value') : fn(['fn', 'cosh'], 'cosh', 'Calculate the hyperbolic cosine of a value'),
      s ? fn(['fn', 'atanh'], 'tanh^-1', 'Calculate the inverse hyperbolic tangent of a value') : fn(['fn', 'tanh'], 'tanh', 'Calculate the hyperbolic tangent of a value'),
      fn(['pi'], 'π', 'Enter pi (3.14159…) (or press p)'),
      state.angle === 'deg' ? fn(['angle'], 'Rad', 'Change angular units to radians') : fn(['angle'], 'Deg', 'Change angular units to degrees')],
  ];
}

function programmerRows() {
  const b = state.base;
  const hex = (d) => digit(d, parseInt(d, 16) < b);
  const p = (key, text, help) => K(key, text, 'fn', help);
  const ops = OPS();
  return [
    [backKey('fn'), p(['open'], '(', 'Open parenthesis'), p(['close'], ')', 'Close parenthesis'), hex('D'), hex('E'), hex('F'), clearKey()],
    [p(['op', 'and'], 'AND', 'Bitwise AND (or press &)'), p(['op', 'or'], 'OR', 'Bitwise OR (or press |)'), p(['op', 'xor'], 'XOR', 'Bitwise XOR (or press ^)'), hex('A'), hex('B'), hex('C'), ops[0]],
    [p(['op', 'nor'], 'NOR', 'Bitwise NOR'), p(['shl1'], '<<', 'Shift value by 1 bit to the left (or press <)'), p(['shr1'], '>>', 'Shift value by 1 bit to the right (or press >)'), hex('7'), hex('8'), hex('9'), ops[1]],
    [p(['fn', 'not'], 'NOT', 'Bitwise NOT (1’s complement) (or press ~)'), p(['op', 'shl'], 'X<<Y', 'Shift value by a number of bits to the left'), p(['op', 'shr'], 'X>>Y', 'Shift value by a number of bits to the right'), hex('4'), hex('5'), hex('6'), ops[2]],
    [p(['fn', 'twosNeg'], 'NEG', 'Negate value (2’s complement)'), p(['fn', 'rol'], 'RoL', 'Rotate value by 1 bit to the left'), p(['fn', 'ror'], 'RoR', 'Rotate value by 1 bit to the right'), hex('1'), hex('2'), hex('3'), ops[3]],
    [p(['op', 'mod'], 'mod', 'Calculate the modulo (remainder) of a value divided by a second value (or press %)'),
      p(['fn', 'flip8'], 'flip_8', 'Flip bytes (0xABCD becomes 0xCDAB)'), p(['fn', 'flip16'], 'flip_16', 'Flip 16-bit words (0xABCD1234 becomes 0x1234ABCD)'),
      K(['digit', 'FF'], 'FF', 'digit', 'FF', { disabled: b !== 16 }), hex('0'), K(['00'], '00', 'digit', '00'), equalsKey(false)],
  ];
}

const RPN_BAR = [
  K(['swap'], 'x↔y', 'bar', 'Swap the bottom two values on the stack (or press Command-E)'),
  K(['rdown'], 'R↓', 'bar', 'Rotate the contents of the stack down (or press Command-Down Arrow)'),
  K(['rup'], 'R↑', 'bar', 'Rotate the contents of the stack up (or press Command-Up Arrow)'),
  K(['drop'], 'drop', 'bar', 'Remove the bottom value from the stack (or press Command-Delete)'),
];

function keyButton(spec) {
  const btn = h('button.calc-key', {
    type: 'button', title: spec.help, 'aria-label': spec.help || undefined,
    disabled: !!spec.disabled, dataset: { style: spec.style },
  });
  if (spec.wide) btn.dataset.wide = '';
  if (typeof spec.text === 'object') btn.innerHTML = ICONS[spec.text.icon];
  // One inline wrapper: flex children ignore vertical-align, which <sup>/<sub> rely on.
  else btn.append(h('span.calc-key-label', {}, spansToNodes(label(spec.text))));
  btn.addEventListener('click', () => {
    if (btn._longPressed) { btn._longPressed = false; return; }
    press(spec.key);
    update();
  });
  if (spec.key[0] === 'back') {
    // "long press to delete all"
    let timer = null;
    const cancel = () => { clearTimeout(timer); timer = null; };
    btn.addEventListener('pointerdown', () => {
      timer = setTimeout(() => { btn._longPressed = true; press(['clearAll']); update(); }, 600);
    });
    btn.addEventListener('pointerup', cancel);
    btn.addEventListener('pointerleave', cancel);
  }
  btn._calcKey = spec.key;
  return btn;
}

// ── Window ──────────────────────────────────────────────────────────────

let modal = null;
let content = null;
let main = null;
let historyEl = null;
let pane = null;
let historyBtn = null;
let keysSignature = '';
let keysEl = null;
let open = false;
let popup = null;           // { el, close } for the open menu or picker

/** WCAG relative luminance of an `rgb(...)` string. */
function luminance(rgb) {
  const [r, g, b] = (rgb.match(/[\d.]+/g) || [0, 0, 0]).slice(0, 3).map(v => {
    const c = Number(v) / 255;
    return c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4;
  });
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
}

/**
 * Operator keys, selected chips and menu highlights sit on the theme accent.
 * Calculator.app uses white there; keep white while it has at least 3:1
 * contrast and switch to a near-black ink on light accents (e.g. Terminal's
 * green), so every preset and custom theme stays readable.
 */
function syncAccentInk() {
  const probe = document.createElement('span');
  probe.style.cssText = 'position:absolute;visibility:hidden;color:var(--red, #e06c75)';
  document.body.append(probe);
  const accent = getComputedStyle(probe).color;
  probe.remove();
  const L = luminance(accent);
  const whiteContrast = 1.05 / (L + 0.05);
  document.documentElement.style.setProperty('--calc-on-accent', whiteContrast >= 3 ? '#fff' : '#111');
}

let accentObserver = null;
function watchTheme() {
  syncAccentInk();
  if (accentObserver) return;
  let queued = false;
  accentObserver = new MutationObserver(() => {
    if (queued) return;
    queued = true;
    requestAnimationFrame(() => { queued = false; syncAccentInk(); });
  });
  accentObserver.observe(document.documentElement, { attributes: true, attributeFilter: ['style', 'class'] });
}

function ensureCss() {
  if (document.querySelector('link[data-calculator-css]')) return;
  document.head.append(h('link', { rel: 'stylesheet', href: CSS_HREF, 'data-calculator-css': '1' }));
}

function registerWindow() {
  Modals.register(MODAL_ID, {
    railBtnId: document.getElementById(RAIL_BTN_ID) ? RAIL_BTN_ID : undefined,
    sidebarBtnId: SIDEBAR_BTN_ID,
    label: 'Calculator',
    icon: DOCK_ICON,
    closeFn: doClose,
    restoreFn: () => { open = true; update(); },
  });
}

function buildModal() {
  ensureCss();
  watchTheme();
  modal = h(`div#${MODAL_ID}.modal`, { style: 'display:none' });
  historyBtn = h('button.calc-tool', {
    type: 'button', html: ICONS.sidebar, title: 'Show History', 'aria-label': 'Show History',
    on: { click: () => { state.showHistory = !state.showHistory; save(); update(); } },
  });
  const modeBtn = h('button.calc-tool', {
    type: 'button', html: ICONS.calculatorBig, title: 'Change Calculator mode', 'aria-label': 'Change Calculator mode', 'aria-haspopup': 'menu',
  });
  modeBtn.addEventListener('click', () => openModeMenu(modeBtn));
  const closeBtn = h('button.close-btn', { type: 'button', title: 'Close', 'aria-label': 'Close Calculator', text: '✖', on: { click: closeCalculator } });
  const header = h('div.modal-header.calc-header', {},
    h('h4', { html: `${ICONS.calculator}<span>Calculator</span>` }),
    historyBtn, modeBtn, closeBtn);
  historyEl = h('aside.calc-history', { 'aria-label': 'History' });
  pane = h('section.calc-pane', { 'aria-label': 'Calculator' });
  main = h('div.calc-main', {}, historyEl, pane);
  content = h('div.modal-content.calc-content', { role: 'region', 'aria-label': 'Calculator', tabindex: '-1' }, header, main);
  content.addEventListener('pointerdown', (e) => {
    // Keep keyboard input routed to the calculator after clicking its keys.
    if (!e.target.closest('input, textarea, select')) requestAnimationFrame(() => {
      if (!content.contains(document.activeElement) || document.activeElement.tagName === 'BUTTON') content.focus({ preventScroll: true });
    });
  });
  content.addEventListener('paste', onPaste);
  content.addEventListener('copy', onCopy);
  modal.append(content);
  document.body.append(modal);
  // Register before the app.js observer sees the new .modal, so it skips its
  // legacy "_" button and the modalManager chip/minimize flow is used instead.
  registerWindow();
  Modals.injectMinimizeButton(modal, MODAL_ID);
  makeWindowDraggable(modal, { content, header, enableResize: false, enableDock: false });
  window.addEventListener('keydown', onKeydown, true);
  window.addEventListener('keyup', onShift, true);
  window.addEventListener('blur', () => { if (shiftHeld) { shiftHeld = false; update(); } });
  window.addEventListener('resize', () => { if (open) update(); });
}

// ── Rendering ───────────────────────────────────────────────────────────

function update() {
  if (!pane) return;
  pane.dataset.mode = state.mode;
  // History needs 220px beside the keypad; when the workspace is too narrow it
  // hides for now without changing the saved preference.
  const roomForHistory = workspaceWidth() - 244 >= (state.mode === 'basic' ? 230 : state.mode === 'scientific' ? 360 : 330);
  const showHistory = state.showHistory && historyAvailable() && roomForHistory;
  main.classList.toggle('calc-with-history', showHistory);
  historyBtn.hidden = !historyAvailable();
  historyBtn.setAttribute('aria-pressed', String(showHistory));
  historyBtn.title = showHistory ? 'Hide History' : 'Show History';
  historyBtn.setAttribute('aria-label', historyBtn.title);
  historyEl.hidden = !showHistory;
  if (showHistory) renderHistory();

  const display = renderDisplay();
  const parts = [];
  if (rpnActive() && state.mode === 'scientific') {
    parts.push(h('div.calc-display-wrap', {}, display, h('div.calc-rpn-bar', {}, RPN_BAR.map(keyButton))));
  } else {
    parts.push(display);
    if (rpnActive()) parts.push(h('div.calc-rpn-bar', {}, RPN_BAR.map(keyButton)));
  }
  if (state.mode === 'programmer') {
    parts.push(renderProgrammerControls());
    if (state.showBinary) parts.push(renderBits());
  }

  // Rebuild the keypad only when its layout or labels change, so a key is not
  // replaced under the pointer on every press.
  const rows = state.mode === 'basic' ? basicColumns(rpnActive())
    : state.mode === 'scientific' ? scientificColumns(rpnActive()).map((r, i) => r.concat(basicColumns(rpnActive())[i]))
      : programmerRows();
  const signature = JSON.stringify(rows.map(r => r.map(k => [k.key, k.text, k.style, !!k.disabled])));
  if (signature !== keysSignature || !keysEl) {
    keysSignature = signature;
    keysEl = h('div.calc-keys', { style: `--calc-cols:${rows[0].length}` }, rows.flat().map(keyButton));
  }
  parts.push(keysEl);
  pane.replaceChildren(...parts);
  requestAnimationFrame(keepOnScreen);
}

function workspaceWidth() {
  const cs = getComputedStyle(document.documentElement);
  const rail = parseFloat(cs.getPropertyValue('--icon-rail-w')) || 0;
  const side = parseFloat(cs.getPropertyValue('--sidebar-w')) || 0;
  return window.innerWidth - (window.innerWidth > 768 ? rail + side : 0);
}

/** A dragged window is pinned with a fixed left/top; when a mode change grows it, pull it back on screen. */
function keepOnScreen() {
  if (!content || content.style.position !== 'fixed' || !open) return;
  const r = content.getBoundingClientRect();
  const left = Math.max(8, Math.min(r.left, window.innerWidth - r.width - 8));
  const top = Math.max(8, Math.min(r.top, window.innerHeight - r.height - 8));
  if (left !== r.left) content.style.left = `${left}px`;
  if (top !== r.top) content.style.top = `${top}px`;
}

function spansEl(cls, spans) {
  const el = h(`div.${cls}`);
  if (cls === 'calc-expr') el.append(h('span', {}, spansToNodes(spans)));
  else el.append(spansToNodes(spans));
  return el;
}

/** Shrinks the main line's font until it fits, like the original (min 42%). */
function fit(el, base) {
  el.style.fontSize = `${base}px`;
  requestAnimationFrame(() => {
    const avail = el.clientWidth;
    const need = el.scrollWidth;
    if (avail > 0 && need > avail) el.style.fontSize = `${Math.max(base * 0.42, base * avail / need)}px`;
  });
}

function mainLine(spans, base = 34, cls = 'calc-main-line') {
  const el = spansEl(cls, spans);
  fit(el, base);
  return el;
}

function resultSpans(c) {
  if (c.error) return [{ text: c.error.message, level: 0 }];
  if (c.kind === 'programmer') {
    const out = [{ text: integerString(c.intResult ?? 0n, state.base), level: 0 }];
    return out.concat([{ text: String(state.base), level: -1 }]);
  }
  return [{ text: format().format(c.result ?? new Dec(0n)), level: 0 }];
}

function standardDisplay(c, showsBase) {
  const parts = [];
  if (c.evaluated) {
    parts.push(spansEl('calc-expr', render(c.evaluated, format(), { showsBase })));
    parts.push(mainLine(resultSpans(c)));
  } else {
    const spans = c.tokens.length
      ? render(c.tokens, format(), { showsBase })
      : [{ text: '0', level: 0 }].concat(showsBase ? [{ text: String(state.base), level: -1 }] : []);
    parts.push(mainLine(spans));
  }
  return parts;
}

function renderDisplay() {
  const display = h('div.calc-display', { 'aria-live': 'polite' });
  if (rpnActive()) {
    const rows = rpnCalc.rows.slice(-3);
    while (rows.length < 3) rows.unshift(null);
    for (const row of rows) {
      const text = !row ? '' : row.kind === 'value' ? format().format(row.value)
        : row.kind === 'typing' ? format().typed(row.text) : row.error.message;
      const el = h('div.calc-rpn-row', { text });
      if (text) fit(el, 30);
      display.append(el);
    }
  } else if (state.convert && state.mode !== 'programmer') {
    display.append(...convertDisplay());
  } else {
    display.append(...standardDisplay(active(), state.mode === 'programmer'));
  }
  const badges = h('div.calc-badges');
  if (state.mode === 'scientific' && state.angle === 'rad') badges.append(h('span', { text: 'Rad' }));
  if (state.mode === 'scientific' && memory) badges.append(h('span', { text: 'M', title: 'A value is stored in memory' }));
  if (state.mode === 'programmer') {
    const ch = characterBadge();
    if (ch !== null) badges.append(h('span.calc-char', { text: ch || ' ' }));
  }
  if (badges.childNodes.length) display.append(badges);
  return display;
}

function characterBadge() {
  const v = BigInt.asUintN(64, currentInt());
  if (state.charView === 'ascii') return v >= 32n && v < 127n ? String.fromCharCode(Number(v)) : '';
  if (state.charView === 'unicode') {
    if (v < 32n || v > 0x10FFFFn || (v >= 0xD800n && v <= 0xDFFFn)) return '';
    return String.fromCodePoint(Number(v));
  }
  return null;
}

// ── Programmer controls ─────────────────────────────────────────────────

function segmented(items, selected, onPick, aria) {
  return h('div.calc-seg', { role: 'group', 'aria-label': aria },
    items.map((text, i) => h('button', {
      type: 'button', text, 'aria-pressed': String(selected === i),
      on: { click: () => { onPick(i); update(); } },
    })));
}

function renderProgrammerControls() {
  const charIndex = state.charView === 'ascii' ? 0 : state.charView === 'unicode' ? 1 : -1;
  return h('div.calc-prog-controls', {},
    segmented(['ASCII', 'Unicode'], charIndex, (i) => {
      const target = i === 0 ? 'ascii' : 'unicode';
      state.charView = state.charView === target ? 'none' : target;
      save();
    }, 'Toggle to show ASCII or Unicode value'),
    h('button.calc-pill', {
      type: 'button', text: state.showBinary ? 'Hide Binary' : 'Show Binary', title: 'Toggle display of binary view',
      on: { click: () => { state.showBinary = !state.showBinary; save(); update(); } },
    }),
    segmented(['8', '10', '16'], [8, 10, 16].indexOf(state.base), (i) => setBase([8, 10, 16][i]),
      'Select a base to change the current base of the numbers'));
}

/** Two rows of eight nibbles, bit 63 top-left to bit 0 bottom-right. Click a bit to flip it. */
function renderBits() {
  const v = BigInt.asUintN(64, currentInt());
  const grid = h('div.calc-bits', { role: 'group', 'aria-label': 'Binary view' });
  const row = (high, labels) => {
    for (let n = 0; n < 8; n++) {
      const nib = h('span.calc-nibble');
      for (let b = 0; b < 4; b++) {
        const bit = high - n * 4 - b;
        const on = ((v >> BigInt(bit)) & 1n) === 1n;
        nib.append(h('button.calc-bit', {
          type: 'button', text: on ? '1' : '0', 'aria-pressed': String(on), title: `Bit ${bit}`,
          on: { click: () => { programmer.base = state.base; programmer.setCurrentOperand(BigInt.asIntN(64, currentInt() ^ (1n << BigInt(bit)))); update(); } },
        }));
      }
      grid.append(nib);
    }
    for (let n = 0; n < 8; n++) {
      const text = n === 0 ? labels[0] : n === 4 ? labels[1] : n === 7 ? labels[2] : '';
      grid.append(h(`span.calc-bit-label${n === 7 ? '.calc-end' : ''}`, { text }));
    }
  };
  row(63, ['63', '47', '32']);
  row(31, ['31', '15', '0']);
  return grid;
}

// ── Convert ─────────────────────────────────────────────────────────────

function unitFor(id) { return findUnit(id, rates); }

function convertDisplay() {
  const c = algebraic;
  const valueSpans = c.evaluated ? resultSpans(c) : (c.tokens.length ? render(c.tokens, format()) : [{ text: '0', level: 0 }]);
  const from = unitFor(state.inUnit);
  const to = unitFor(state.outUnit);
  let resultText = '—';
  const value = displayedValue();
  if (from && to) {
    const out = convert(value ?? new Dec(0n), from, to);
    if (out) {
      const f = format();
      if (to.category === 'Currency' && f.places === null) f.places = 2;
      resultText = f.format(out);
    }
  } else if ((from?.category ?? to?.category ?? '') === 'Currency' || state.inUnit.startsWith('currency.')) {
    resultText = ratesLoading ? '…' : '—';
  }
  return [
    mainLine(valueSpans, 34),
    h('div.calc-convert-row', {}, unitChip(true, from)),
    h('div.calc-swap-row', {},
      h('button.calc-swap', {
        type: 'button', html: ICONS.swap, title: 'Swap Units', 'aria-label': 'Swap Units',
        on: { click: () => { [state.inUnit, state.outUnit] = [state.outUnit, state.inUnit]; save(); update(); } },
      }),
      h('hr')),
    mainLine([{ text: resultText, level: 0 }], 34, 'calc-main-line.calc-convert-result'),
    h('div.calc-convert-row', {}, unitChip(false, to)),
  ];
}

function unitChip(isInput, unit) {
  const chip = h('button.calc-unit-chip', {
    type: 'button', title: isInput ? 'Input Unit' : 'Result Unit',
    'aria-label': `${isInput ? 'Input unit' : 'Result unit'}: ${unit ? unit.name : 'none'}`, 'aria-haspopup': 'dialog',
  }, h('span', { text: unit ? unit.abbr : (state[isInput ? 'inUnit' : 'outUnit'].split('.')[1] || '—') }),
  h('span.calc-chevrons', { html: ICONS.chevrons }));
  chip.addEventListener('click', () => openUnitPicker(chip, isInput));
  return chip;
}

function loadRates() {
  if (ratesLoading) return;
  ratesLoading = true;
  refreshRates().then((r) => { rates = r; }).finally(() => { ratesLoading = false; update(); refreshPicker?.(); });
}

function selectUnit(unit, isInput) {
  const key = isInput ? 'inUnit' : 'outUnit';
  const otherKey = isInput ? 'outUnit' : 'inUnit';
  state[key] = unit.id;
  const other = unitFor(state[otherKey]);
  if (!other || other.category !== unit.category) {
    const pool = unit.category === 'Currency' ? currencyUnits(rates) : UNITS.filter(x => x.category === unit.category);
    const replacement = pool.find(x => x.id !== unit.id && (unit.category !== 'Currency' || x.abbr === 'EUR' || x.abbr === 'USD')) || pool.find(x => x.id !== unit.id);
    if (replacement) state[otherKey] = replacement.id;
  }
  state.recentUnits = [unit.id, ...state.recentUnits.filter(id => id !== unit.id)].slice(0, 8);
  save();
}

let refreshPicker = null;

function openUnitPicker(anchor, isInput) {
  closePopup();
  const selectedId = () => state[isInput ? 'inUnit' : 'outUnit'];
  let category = unitFor(selectedId())?.category || (selectedId().startsWith('currency.') ? 'Currency' : 'Length');
  let query = '';
  const panel = h('div.calc-picker', { role: 'dialog', 'aria-label': isInput ? 'Input Unit' : 'Result Unit' });
  const search = h('input.calc-picker-search', { type: 'search', placeholder: 'Search all units', 'aria-label': 'Search all units' });
  const chips = h('div.calc-picker-chips', { role: 'tablist', 'aria-label': 'Category' });
  const list = h('div.calc-picker-list', { role: 'listbox' });
  const footer = h('div.calc-picker-footer');
  panel.append(search, chips, list, footer);

  const draw = () => {
    chips.hidden = !!query;
    chips.replaceChildren();
    const cats = (state.recentUnits.length ? ['Recent Units'] : []).concat(CATEGORIES);
    for (const c of cats) {
      const on = c === category;
      const chip = h('button.calc-chip', {
        type: 'button', text: c, 'aria-pressed': String(on), role: 'tab',
        on: { click: () => { category = c; if (c === 'Currency') loadRates(); draw(); } },
      });
      chips.append(chip);
      if (on) requestAnimationFrame(() => chip.scrollIntoView({ inline: 'center', block: 'nearest' }));
    }
    let items;
    if (query) {
      const q = query.toLowerCase();
      items = UNITS.concat(currencyUnits(rates)).filter(x => x.name.toLowerCase().includes(q) || x.abbr.toLowerCase().includes(q));
    } else if (category === 'Recent Units') {
      items = state.recentUnits.map(unitFor).filter(Boolean);
    } else {
      items = unitsIn(category, rates);
    }
    list.replaceChildren();
    if (!items.length) {
      if (query) list.append(h('div.calc-picker-empty', {}, h('strong', { text: `No Results for “${query}”` }), h('p', { text: 'Check the spelling or try a new search.' })));
      else if (category === 'Currency') {
        list.append(h('div.calc-picker-empty', {},
          h('strong', { text: ratesLoading ? 'Loading rates…' : 'Currency Rates Unavailable' }),
          ratesLoading ? null : h('p', { text: 'Exodus could not reach the exchange-rate service. Check the internet connection and try again.' })));
      }
    }
    for (const unit of items) {
      const on = unit.id === selectedId();
      const row = h('button.calc-unit', {
        type: 'button', role: 'option', 'aria-selected': String(on),
        on: { click: () => { selectUnit(unit, isInput); closePopup(); update(); } },
      }, h('span.calc-unit-check', { text: on ? '✓' : '' }),
      h('span', {}, h('span.calc-unit-name', { text: unit.name }), h('span.calc-unit-abbr', { text: unit.abbr })));
      list.append(row);
      if (on) requestAnimationFrame(() => row.scrollIntoView({ block: 'center' }));
    }
    footer.replaceChildren();
    footer.hidden = !(category === 'Currency' && !query);
    if (!footer.hidden) {
      footer.append(h('span', { text: `Rates: ${(rates?.source || 'ExchangeRate-API').replace(/\s*\(.*\)$/, '')}`, title: rates?.source || '' }));
      if (rates?.updated) footer.append(h('span', { text: `Updated ${relativeTime(rates.updated * 1000)}${rates.stale ? ' (offline copy)' : ''}` }));
    }
  };
  refreshPicker = draw;
  search.addEventListener('input', () => { query = search.value.trim(); if (query) loadRates(); draw(); });
  if (category === 'Currency') loadRates();
  draw();

  panel.style.zIndex = String(topPortalZ());
  document.body.append(panel);
  // Beside the window like Calculator.app's popover; inside it only when neither side has room.
  const a = anchor.getBoundingClientRect();
  const win = content.getBoundingClientRect();
  const r = panel.getBoundingClientRect();
  let left = win.right + 10;
  if (left + r.width > window.innerWidth - 8) left = win.left - r.width - 10;
  if (left < 8) left = Math.max(8, Math.min(a.right + 10, window.innerWidth - r.width - 8));
  const top = Math.min(Math.max(8, a.top + a.height / 2 - r.height / 2), window.innerHeight - r.height - 8);
  panel.style.left = `${left}px`;
  panel.style.top = `${top}px`;
  const close = bindMenuDismiss(panel, () => { panel.remove(); refreshPicker = null; popup = null; }, (e) => !panel.contains(e.target) && !anchor.contains(e.target));
  popup = { el: panel, close };
  requestAnimationFrame(() => search.focus());
}

function relativeTime(ms) {
  const sec = Math.round((ms - Date.now()) / 1000);
  const abs = Math.abs(sec);
  const rtf = new Intl.RelativeTimeFormat(undefined, { numeric: 'auto' });
  if (abs < 60) return rtf.format(sec, 'second');
  if (abs < 3600) return rtf.format(Math.round(sec / 60), 'minute');
  if (abs < 86400) return rtf.format(Math.round(sec / 3600), 'hour');
  return rtf.format(Math.round(sec / 86400), 'day');
}

// ── Menus ───────────────────────────────────────────────────────────────

function closePopup() {
  if (popup) { const p = popup; popup = null; p.close?.(); }
}

function menu(x, y, items, anchor = null) {
  closePopup();
  const el = h('div.calc-menu', { role: 'menu' });
  for (const it of items) {
    if (it === '-') { el.append(h('div.calc-menu-sep')); continue; }
    if (it.node) { el.append(it.node); continue; }
    el.append(h(`button.calc-menu-item${it.danger ? '.calc-danger' : ''}`, {
      type: 'button', role: it.checked === undefined ? 'menuitem' : 'menuitemcheckbox',
      'aria-checked': it.checked === undefined ? undefined : String(!!it.checked),
      disabled: !!it.disabled,
      on: { click: () => { closePopup(); it.action?.(); update(); } },
    }, h('span.calc-menu-check', { text: it.checked ? '✓' : '' }),
    it.icon ? h('span.calc-menu-icon', { html: ICONS[it.icon] }) : null,
    h('span', { text: it.label })));
  }
  el.style.zIndex = String(topPortalZ());
  document.body.append(el);
  const r = el.getBoundingClientRect();
  el.style.left = `${Math.max(6, Math.min(x, window.innerWidth - r.width - 6))}px`;
  el.style.top = `${Math.max(6, Math.min(y, window.innerHeight - r.height - 6))}px`;
  const close = bindMenuDismiss(el, () => { el.remove(); popup = null; },
    anchor ? (e) => !el.contains(e.target) && !anchor.contains(e.target) : undefined);
  popup = { el, close };
  requestAnimationFrame(() => el.querySelector('button:not(:disabled)')?.focus());
}

function openModeMenu(anchor) {
  if (popup) { closePopup(); return; }
  const prog = state.mode === 'programmer';
  const places = h('div', {},
    h('div.calc-menu-label', { text: 'Decimal Places' }),
    h('div.calc-menu-places', {}, [null, ...Array.from({ length: 16 }, (_, i) => i)].map(p => h('button', {
      type: 'button', text: p === null ? 'Auto' : String(p), 'aria-pressed': String(state.places === p),
      on: { click: () => { state.places = p; save(); closePopup(); update(); } },
    }))));
  const r = anchor.getBoundingClientRect();
  menu(r.left - 150, r.bottom + 6, [
    { label: 'Basic', icon: 'basic', checked: state.mode === 'basic', action: () => setMode('basic') },
    { label: 'Scientific', icon: 'scientific', checked: state.mode === 'scientific', action: () => setMode('scientific') },
    { label: 'Programmer', icon: 'programmer', checked: state.mode === 'programmer', action: () => setMode('programmer') },
    '-',
    { label: 'Math Notes…', icon: 'notes', action: openNotes },
    '-',
    { label: 'Convert', checked: state.convert, disabled: prog, action: toggleConvert },
    { label: 'RPN Mode', checked: state.rpn, disabled: prog, action: toggleRPN },
    '-',
    { label: 'Thousands Separator', checked: state.thousands, action: () => { state.thousands = !state.thousands; save(); } },
    { node: places },
  ], anchor);
}

/** Calculator.app's Math Notes lives in Notes; Exodus has its own Notes tool. */
function openNotes() {
  const btn = document.getElementById('tool-notes-btn');
  if (btn) btn.click();
}

// ── History ─────────────────────────────────────────────────────────────

function historySections() {
  const now = new Date();
  const startOfDay = new Date(now.getFullYear(), now.getMonth(), now.getDate()).getTime();
  const day = 86400000;
  const groups = new Map();
  for (const rec of state.history) {
    let title;
    if (rec.at >= startOfDay) title = 'Today';
    else if (rec.at >= startOfDay - day) title = 'Yesterday';
    else if (rec.at >= startOfDay - 7 * day) title = 'Previous 7 Days';
    else if (rec.at >= startOfDay - 30 * day) title = 'Previous 30 Days';
    else title = new Date(rec.at).toLocaleDateString(undefined, { month: 'long', year: 'numeric' });
    if (!groups.has(title)) groups.set(title, []);
    groups.get(title).push(rec);
  }
  return [...groups];
}

/** Observed: the sidebar shows 199.99+7.5% as 214.989 while the display shows 214.98925. */
function historyResult(rec) {
  if (rec.mode === 'programmer') return integerString(BigInt.asIntN(64, Dec.parse(rec.result).trunc().toBigInt()), rec.base);
  const f = format();
  if (f.places === null) {
    f.places = 3;
    const text = f.format(Dec.parse(rec.result));
    return text.includes('e') || !text.includes(f.decimalSep) ? text : text.replace(/0+$/, '').replace(new RegExp(`\\${f.decimalSep}$`), '');
  }
  return f.format(Dec.parse(rec.result));
}

function renderHistory() {
  historyEl.replaceChildren();
  if (!state.history.length) {
    historyEl.append(h('div.calc-history-empty', { text: 'No History' }));
    return;
  }
  for (const [title, records] of historySections()) {
    historyEl.append(h('h5', { text: title }));
    for (const rec of records) {
      const result = historyResult(rec);
      const btn = h('button.calc-record', {
        type: 'button', title: 'Use this result',
        on: { click: () => { useRecord(rec); update(); } },
      }, h('span.calc-record-expr', {}, spansToNodes(rec.expr)), h('span.calc-record-result', { text: result }));
      btn.addEventListener('contextmenu', (e) => {
        e.preventDefault();
        menu(e.clientX, e.clientY, [
          { label: 'Copy Result', action: () => copyText(result) },
          { label: 'Copy Expression', action: () => copyText(plainText(rec.expr)) },
          '-',
          { label: 'Delete', danger: true, action: () => { state.history = state.history.filter(r => r.id !== rec.id); save(); } },
          { label: 'Clear History…', danger: true, action: confirmClearHistory },
        ]);
      });
      historyEl.append(btn);
    }
  }
}

function useRecord(rec) {
  const v = Dec.parse(rec.result);
  if (!v) return;
  if (rpnActive()) rpnCalc.push(v); else active().inputValue(v);
}

function confirmClearHistory() {
  const backdrop = h('div.calc-sheet-backdrop');
  const done = () => backdrop.remove();
  backdrop.append(h('div.calc-sheet', { role: 'alertdialog', 'aria-label': 'Clear History' },
    h('h5', { text: 'Are you sure you want to delete all calculations?' }),
    h('p', { text: 'All calculations will be deleted. This action cannot be undone.' }),
    h('div.calc-sheet-actions', {},
      h('button', { type: 'button', text: 'Cancel', on: { click: done } }),
      h('button.calc-danger-btn', { type: 'button', text: 'Delete All', on: { click: () => { state.history = []; save(); done(); update(); } } }))));
  backdrop.addEventListener('mousedown', (e) => { if (e.target === backdrop) done(); });
  content.append(backdrop);
  requestAnimationFrame(() => backdrop.querySelector('button')?.focus());
}

// ── Clipboard ───────────────────────────────────────────────────────────

function copyText(text) {
  navigator.clipboard?.writeText(text).catch(() => {});
}

function resultText() {
  const v = displayedValue();
  if (!v) return '';
  if (state.mode === 'programmer') return integerString(BigInt.asIntN(64, v.trunc().toBigInt()), state.base);
  const f = format();
  f.grouping = false;
  return f.format(v);
}

function onCopy(e) {
  if (window.getSelection()?.toString()) return;    // copying selected text works as usual
  const text = resultText();
  if (!text) return;
  e.clipboardData.setData('text/plain', text);
  e.preventDefault();
}

function onPaste(e) {
  if (e.target.closest?.('input, textarea')) return;
  let text = (e.clipboardData?.getData('text/plain') || '').trim();
  if (!text) return;
  e.preventDefault();
  if (state.mode === 'programmer') {
    text = text.replace(/^0x/i, '').toUpperCase();
    let v = 0n;
    for (const ch of text) {
      const d = parseInt(ch, 16);
      if (Number.isNaN(d) || d >= state.base) return;
      v = v * BigInt(state.base) + BigInt(d);
    }
    programmer.base = state.base;
    programmer.inputValue(new Dec(BigInt.asIntN(64, v)));
  } else {
    const f = format();
    const v = Dec.parse(text.split(f.groupSep).join('').replace(f.decimalSep, '.'));
    if (!v) return;
    if (rpnActive()) rpnCalc.push(v); else algebraic.inputValue(v);
  }
  update();
}

// ── Keyboard (shortcuts named in the app's own tooltips) ────────────────

function onShift(e) {
  if (e.key !== 'Shift' || !open) return;
  const held = e.type === 'keydown' ? true : false;
  if (state.mode === 'scientific' && held !== shiftHeld) { shiftHeld = held; update(); }
}

function flash(key) {
  const btn = keysEl && [...keysEl.children].find(b => JSON.stringify(b._calcKey) === JSON.stringify(key));
  if (!btn) return;
  btn.classList.add('calc-pressed');
  setTimeout(() => btn.classList.remove('calc-pressed'), 110);
}

function keyFor(e) {
  const prog = state.mode === 'programmer';
  const sci = state.mode === 'scientific';
  const mod = e.metaKey || e.ctrlKey;
  if (mod) {
    if (!rpnActive()) return null;
    if (e.key === 'Backspace') return ['drop'];
    if (e.key === 'ArrowUp') return ['rup'];
    if (e.key === 'ArrowDown') return ['rdown'];
    if (e.key.toLowerCase() === 'e') return ['swap'];
    return null;
  }
  if (e.altKey) {
    if (e.code === 'KeyV') return ['fn', 'sqrt'];
    if (e.code === 'Minus') return ['sign'];
    return null;
  }
  const k = e.key;
  if (k === 'Enter' || k === '=') return ['equals'];
  if (k === 'Backspace' || k === 'Delete') return ['back'];
  if (/^[0-9]$/.test(k)) return ['digit', k];
  if (prog && /^[a-fA-F]$/.test(k)) return ['digit', k.toUpperCase()];
  if (k === '.' || k === ',') return prog ? null : ['point'];
  if (k === '+') return ['op', 'add'];
  if (k === '-') return ['op', 'sub'];
  if (k === '*' || k === 'x' || k === 'X') return ['op', 'mul'];
  if (k === '/' || k === '÷') return ['op', 'div'];
  if (k === '%') return prog ? ['op', 'mod'] : ['post', 'pct'];
  if (k === '(') return ['open'];
  if (k === ')') return ['close'];
  if (k === '^') return prog ? ['op', 'xor'] : ['op', 'pow'];
  if (k === '!' && !prog) return ['post', 'fact'];
  if (sci && k === 'p') return ['pi'];
  if (sci && k === 'e') return ['fn', 'ln'];
  if (sci && k === 'E') return ['op', 'ee'];
  if (prog && k === '&') return ['op', 'and'];
  if (prog && k === '|') return ['op', 'or'];
  if (prog && k === '~') return ['fn', 'not'];
  if (prog && k === '<') return ['shl1'];
  if (prog && k === '>') return ['shr1'];
  return null;
}

function onKeydown(e) {
  if (!open || !modal || modal.classList.contains('hidden') || modal.style.display === 'none') return;
  if (e.key === 'Shift') { onShift(e); return; }
  if (!content.contains(document.activeElement)) return;
  const t = e.target;
  if (t && (t.tagName === 'INPUT' || t.tagName === 'TEXTAREA' || t.isContentEditable)) return;
  if (popup) return;   // menus and the unit picker handle their own keys
  if (e.key === 'Escape') {
    if (content.querySelector('.calc-sheet-backdrop')) {
      content.querySelector('.calc-sheet-backdrop').remove();
      e.preventDefault(); e.stopImmediatePropagation();
      return;
    }
    // Esc clears first (Calculator.app); once already clear it closes the window as usual in Exodus.
    if (clearLabel() === 'C' || (!rpnActive() && active().showingResult)) {
      press(['clear']); update();
      e.preventDefault(); e.stopImmediatePropagation();
    }
    return;
  }
  const key = keyFor(e);
  if (!key) return;
  e.preventDefault();
  e.stopImmediatePropagation();
  press(key);
  flash(key);
  update();
}

// ── Public API ──────────────────────────────────────────────────────────

export function openCalculator() {
  if (Modals.isMinimized(MODAL_ID)) {
    Modals.restore(MODAL_ID);
    open = true;
    update();
    return;
  }
  if (!modal) buildModal();
  if (!Modals.isRegistered(MODAL_ID)) registerWindow();
  open = true;
  modal.classList.remove('hidden', 'modal-minimized');
  modal.style.display = 'flex';
  if (state.convert && (state.inUnit.startsWith('currency.') || state.outUnit.startsWith('currency.'))) loadRates();
  update();
  requestAnimationFrame(() => content.focus({ preventScroll: true }));
}

function doClose() {
  open = false;
  closePopup();
  shiftHeld = false;
  if (modal) {
    modal.style.display = 'none';
    modal.classList.add('hidden');
  }
}

export function closeCalculator() {
  if (Modals.isRegistered(MODAL_ID)) Modals.close(MODAL_ID);
  else doClose();
}

export function isCalculatorOpen() {
  return open && !Modals.isMinimized(MODAL_ID);
}

/** Sidebar click: closed → open, open → close, minimized → restore. */
export function toggleCalculator() {
  if (Modals.isMinimized(MODAL_ID)) { Modals.restore(MODAL_ID); open = true; update(); return; }
  if (isCalculatorOpen()) closeCalculator(); else openCalculator();
}

export default { openCalculator, closeCalculator, isCalculatorOpen, toggleCalculator };
