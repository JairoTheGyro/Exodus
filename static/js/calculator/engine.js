/**
 * Calculator — the DOM-free engine: tokens, a tolerant parser, decimal and
 * 64-bit evaluators, display formatting, span rendering, the expression-entry
 * calculator (Basic/Scientific/Programmer) and the RPN stack.
 *
 * Behaviour reproduces probes of macOS Calculator 12.0, for example
 * `12+3×4=` → 24, `2+3===` → 11 (line shows `8+3`), `2+3%=` → 2.06,
 * `1÷0` → Undefined, ≤ 8 fraction digits, e-notation at ≥ 1e20 or < 1e-8.
 */

import { Dec, ZERO, ONE, PI, E } from './decimal.js';

// ── Tokens ──────────────────────────────────────────────────────────────

/** Infix operators and their precedence (higher binds tighter). */
export const BINARY = {
  or: 1, xor: 1, nor: 1,
  and: 2,
  shl: 3, shr: 3,
  add: 4, sub: 4,
  mul: 5, div: 5, mod: 5,
  pow: 6, rpow: 6, root: 6, logy: 6, ee: 6,
};

const SYMBOL = {
  add: '+', sub: '−', mul: '×', div: '÷', ee: 'E', mod: ' mod ',
  and: ' AND ', or: ' OR ', xor: ' XOR ', nor: ' NOR ', shl: '<<', shr: '>>',
};

export const T = {
  num: (text, base = 10) => ({ t: 'num', text, base }),
  constant: (c) => ({ t: 'const', c }),         // 'pi' | 'e' | Dec
  bin: (op) => ({ t: 'bin', op }),
  open: () => ({ t: 'open' }),
  close: () => ({ t: 'close' }),
  pre: (fn) => ({ t: 'pre', fn }),             // always followed by open
  post: (op) => ({ t: 'post', op }),            // sq | cube | fact | pct
};

const endsOperand = (tok) => !!tok && (tok.t === 'num' || tok.t === 'const' || tok.t === 'close' || tok.t === 'post');

export class CalcError extends Error {
  constructor(kind) {
    super(kind === 'undefined' ? 'Undefined' : 'Error');
    this.kind = kind;
  }
}
const undefinedError = () => new CalcError('undefined');
const domainError = () => new CalcError('domain');

// ── Parser ──────────────────────────────────────────────────────────────

/**
 * Builds a tree from tokens, accepting incomplete input (`2+`, `(3+4`) so
 * the same tree drives live rendering and evaluation.
 */
export function parse(tokens) {
  if (!tokens.length) return null;
  let i = 0;
  const peek = () => tokens[i];
  const atEnd = () => i >= tokens.length;

  function parenthesised() {
    if (atEnd()) return [null, false];
    if (peek().t === 'close') { i++; return [null, true]; }
    const inner = expression(0);
    if (!atEnd() && peek().t === 'close') { i++; return [inner, true]; }
    return [inner, false];
  }

  function primary() {
    const tok = peek();
    if (!tok) return { k: 'empty' };
    switch (tok.t) {
      case 'num': i++; return { k: 'num', text: tok.text, base: tok.base };
      case 'const': i++; return { k: 'const', c: tok.c };
      case 'open': { i++; const [inner, closed] = parenthesised(); return { k: 'group', inner, closed }; }
      case 'pre': {
        i++;
        if (!atEnd() && peek().t === 'open') i++;
        const [inner, closed] = parenthesised();
        return { k: 'pre', fn: tok.fn, inner, closed };
      }
      default: return { k: 'empty' };
    }
  }

  function expression(min) {
    let lhs = primary();
    while (!atEnd()) {
      const tok = peek();
      if (tok.t === 'post') { i++; lhs = { k: 'post', op: tok.op, x: lhs }; continue; }
      if (tok.t === 'bin' && BINARY[tok.op] >= min) {
        i++;
        if (atEnd() || peek().t === 'close') { lhs = { k: 'bin', op: tok.op, l: lhs, r: null }; continue; }
        const next = tok.op === 'pow' ? BINARY[tok.op] : BINARY[tok.op] + 1;
        lhs = { k: 'bin', op: tok.op, l: lhs, r: expression(next) };
        continue;
      }
      break;
    }
    return lhs;
  }

  let node = expression(0);
  while (!atEnd()) {
    i++;   // skip a stray token (e.g. an unmatched close) and keep going
    if (!atEnd()) node = { k: 'bin', op: 'mul', l: node, r: expression(0) };
  }
  return node;
}

// ── Decimal evaluator ───────────────────────────────────────────────────

const fromDouble = (v) => {
  if (Number.isNaN(v)) throw domainError();
  if (!Number.isFinite(v)) throw undefinedError();
  return Dec.fromNumber(v);
};

export function parseNumber(text, base = 10) {
  if (base !== 10) return Dec.from(BigInt.asIntN(64, parseIntBig(text, base)));
  let t = text.endsWith('.') ? text.slice(0, -1) : text;
  if (t === '' || t === '-') return ZERO;
  return Dec.parse(t) ?? ZERO;
}

function parseIntBig(text, base) {
  const neg = text.startsWith('-');
  const digits = neg ? text.slice(1) : text;
  let v = 0n;
  for (const ch of digits.toUpperCase()) {
    const d = parseInt(ch, 36);
    if (Number.isNaN(d) || d >= base) break;
    v = v * BigInt(base) + BigInt(d);
  }
  return neg ? -v : v;
}

function intPow(a, b) {
  const n = b.toSafeInt();
  if (n !== null && Math.abs(n) <= 400) {
    if (n < 0 && a.isZero) throw undefinedError();
    return a.powInt(n);
  }
  if (a.sign < 0) throw domainError();
  return fromDouble(Math.pow(a.toNumber(), b.toNumber()));
}

function factorial(x) {
  const n = x.toSafeInt();
  if (n !== null) {
    if (n < 0 || n > 170) throw domainError();
    let r = 1n;
    for (let k = 2n; k <= BigInt(n); k++) r *= k;
    return new Dec(r);
  }
  if (x.sign < 0) throw domainError();
  return fromDouble(gamma(x.toNumber() + 1));
}

/** Lanczos approximation for non-integer factorials. */
function gamma(z) {
  if (z < 0.5) return Math.PI / (Math.sin(Math.PI * z) * gamma(1 - z));
  const g = 7;
  const c = [0.99999999999980993, 676.5203681218851, -1259.1392167224028, 771.32342877765313,
    -176.61502916214059, 12.507343278686905, -0.13857109526572012, 9.9843695780195716e-6, 1.5056327351493116e-7];
  z -= 1;
  let x = c[0];
  for (let k = 1; k < g + 2; k++) x += c[k] / (z + k);
  const t = z + g + 0.5;
  return Math.sqrt(2 * Math.PI) * Math.pow(t, z + 0.5) * Math.exp(-t) * x;
}

export class Evaluator {
  constructor(angle = 'deg') { this.angle = angle; }

  evaluate(node) {
    switch (node.k) {
      case 'empty': return ZERO;
      case 'num': return parseNumber(node.text, node.base);
      case 'const': return node.c === 'pi' ? PI : node.c === 'e' ? E : node.c;
      case 'group': return node.inner ? this.evaluate(node.inner) : ZERO;
      case 'pre': return this.apply(node.fn, node.inner ? this.evaluate(node.inner) : ZERO);
      case 'post': {
        const x = this.evaluate(node.x);
        if (node.op === 'sq') return x.mul(x);
        if (node.op === 'cube') return x.mul(x).mul(x);
        if (node.op === 'fact') return factorial(x);
        return x.div(100);
      }
      case 'bin': {
        const a = this.evaluate(node.l);
        if (!node.r) return this.binary(node.op, a, a);   // `2+=` reuses the left operand
        // `a ± b%` is "a plus b percent of a": 200+10% = 220, 2+3% = 2.06.
        if ((node.op === 'add' || node.op === 'sub') && node.r.k === 'post' && node.r.op === 'pct') {
          const share = a.mul(this.evaluate(node.r.x)).div(100);
          return node.op === 'add' ? a.add(share) : a.sub(share);
        }
        return this.binary(node.op, a, this.evaluate(node.r));
      }
      default: return ZERO;
    }
  }

  binary(op, a, b) {
    switch (op) {
      case 'add': return a.add(b);
      case 'sub': return a.sub(b);
      case 'mul': return a.mul(b);
      case 'div': if (b.isZero) throw undefinedError(); return a.div(b);
      case 'mod': {
        if (b.isZero) throw undefinedError();
        return a.sub(a.div(b).trunc().mul(b));
      }
      case 'pow': return intPow(a, b);
      case 'rpow': return intPow(b, a);
      case 'root': {
        if (b.isZero) throw undefinedError();
        const n = b.toSafeInt();
        if (a.sign < 0 && n !== null && n % 2 !== 0) return fromDouble(-Math.pow(-a.toNumber(), 1 / b.toNumber()));
        if (a.sign < 0) throw domainError();
        return fromDouble(Math.pow(a.toNumber(), 1 / b.toNumber()));
      }
      case 'logy':
        if (a.sign <= 0 || b.sign <= 0 || b.eq(ONE)) throw domainError();
        return fromDouble(Math.log(a.toNumber()) / Math.log(b.toNumber()));
      case 'ee': return a.mul(intPow(new Dec(10n), b));
      default:
        return new Dec(intBinary(op, BigInt.asIntN(64, a.trunc().toBigInt()), BigInt.asIntN(64, b.trunc().toBigInt())));
    }
  }

  apply(fn, x) {
    const deg = this.angle === 'deg';
    const toRad = deg ? Math.PI / 180 : 1;
    const fromRad = deg ? 180 / Math.PI : 1;
    const d = x.toNumber();
    switch (fn) {
      case 'sin': case 'cos': case 'tan': {
        let a = x;
        if (deg) {
          // Reduce exactly so sin(180) is 0 rather than 1.2e-16.
          a = a.sub(a.div(360).floor().mul(360));
          if (fn === 'tan' && (a.eq(90) || a.eq(270))) throw domainError();
        }
        const r = a.toNumber() * toRad;
        const v = fn === 'sin' ? Math.sin(r) : fn === 'cos' ? Math.cos(r) : Math.tan(r);
        return fromDouble(Math.abs(v) < 1e-15 ? 0 : v);
      }
      case 'asin': if (d < -1 || d > 1) throw domainError(); return fromDouble(Math.asin(d) * fromRad);
      case 'acos': if (d < -1 || d > 1) throw domainError(); return fromDouble(Math.acos(d) * fromRad);
      case 'atan': return fromDouble(Math.atan(d) * fromRad);
      case 'sinh': return fromDouble(Math.sinh(d));
      case 'cosh': return fromDouble(Math.cosh(d));
      case 'tanh': return fromDouble(Math.tanh(d));
      case 'asinh': return fromDouble(Math.asinh(d));
      case 'acosh': if (d < 1) throw domainError(); return fromDouble(Math.acosh(d));
      case 'atanh': if (d <= -1 || d >= 1) throw domainError(); return fromDouble(Math.atanh(d));
      case 'sqrt': if (x.sign < 0) throw domainError(); return fromDouble(Math.sqrt(d));
      case 'cbrt': return fromDouble(Math.cbrt(d));
      case 'ln': if (x.sign <= 0) throw domainError(); return fromDouble(Math.log(d));
      case 'log10': {
        if (x.sign <= 0) throw domainError();
        if (x.m === 1n || x.m === -1n) return new Dec(BigInt(x.e));   // exact powers of ten
        return fromDouble(Math.log10(d));
      }
      case 'log2': if (x.sign <= 0) throw domainError(); return fromDouble(Math.log2(d));
      case 'exp': return fromDouble(Math.exp(d));
      case 'tenPow': return intPow(new Dec(10n), x);
      case 'twoPow': return intPow(new Dec(2n), x);
      case 'recip': if (x.isZero) throw undefinedError(); return ONE.div(x);
      case 'neg': return x.neg();
      default: return new Dec(intUnary(fn, BigInt.asIntN(64, x.trunc().toBigInt())));
    }
  }
}

// ── 64-bit integer evaluator (Programmer) ───────────────────────────────

const I64 = (v) => BigInt.asIntN(64, v);
const U64 = (v) => BigInt.asUintN(64, v);

export function intBinary(op, a, b) {
  switch (op) {
    case 'add': return I64(a + b);
    case 'sub': return I64(a - b);
    case 'mul': return I64(a * b);
    case 'div': if (b === 0n) throw undefinedError(); return I64(a / b);
    case 'mod': if (b === 0n) throw undefinedError(); return I64(a % b);
    case 'and': return I64(a & b);
    case 'or': return I64(a | b);
    case 'xor': return I64(a ^ b);
    case 'nor': return I64(~(a | b));
    case 'shl': return b < 0n || b >= 64n ? 0n : I64(U64(a) << b);
    case 'shr': return b < 0n || b >= 64n ? 0n : I64(U64(a) >> b);
    case 'pow': case 'rpow': {
      const [x, y] = op === 'pow' ? [a, b] : [b, a];
      if (y < 0n) return 0n;
      let r = 1n;
      for (let k = 0n; k < y && k < 64n; k++) r = I64(r * x);
      return r;
    }
    default: return a;
  }
}

export function intUnary(fn, x) {
  const u = U64(x);
  switch (fn) {
    case 'not': return I64(~x);
    case 'neg': case 'twosNeg': return I64(-x);
    case 'rol': return I64((u << 1n) | (u >> 63n));
    case 'ror': return I64((u >> 1n) | (u << 63n));
    case 'flip8': {     // 0xABCD → 0xCDAB
      const low = u & 0xFFFFn;
      return I64((u & ~0xFFFFn) | ((low & 0xFFn) << 8n) | (low >> 8n));
    }
    case 'flip16': {    // 0xABCD1234 → 0x1234ABCD
      const low = u & 0xFFFFFFFFn;
      return I64((u & ~0xFFFFFFFFn) | ((low & 0xFFFFn) << 16n) | (low >> 16n));
    }
    default: return x;
  }
}

export function evaluateInt(node) {
  switch (node.k) {
    case 'empty': return 0n;
    case 'num': return node.base === 10 ? I64(parseNumber(node.text).trunc().toBigInt()) : I64(parseIntBig(node.text, node.base));
    case 'const': return node.c instanceof Dec ? I64(node.c.trunc().toBigInt()) : 0n;
    case 'group': return node.inner ? evaluateInt(node.inner) : 0n;
    case 'pre': return intUnary(node.fn, node.inner ? evaluateInt(node.inner) : 0n);
    case 'post': {
      const x = evaluateInt(node.x);
      if (node.op === 'sq') return I64(x * x);
      if (node.op === 'cube') return I64(x * x * x);
      if (node.op === 'fact') {
        if (x < 0n) throw domainError();
        let r = 1n;
        for (let k = 2n; k <= x && k <= 25n; k++) r = I64(r * k);
        return r;
      }
      return x / 100n;
    }
    case 'bin': {
      const a = evaluateInt(node.l);
      return intBinary(node.op, a, node.r ? evaluateInt(node.r) : a);
    }
    default: return 0n;
  }
}

export function integerString(v, base) {
  return base === 10 ? I64(v).toString() : U64(v).toString(base).toUpperCase();
}

// ── Formatting ──────────────────────────────────────────────────────────

const LOCALE_PARTS = (() => {
  try {
    const parts = new Intl.NumberFormat().formatToParts(12345.6);
    return {
      group: parts.find(p => p.type === 'group')?.value ?? ',',
      decimal: parts.find(p => p.type === 'decimal')?.value ?? '.',
    };
  } catch (_) {
    return { group: ',', decimal: '.' };
  }
})();

export const MAX_FRACTION_DIGITS = 8;
const SCI_DIGITS = 8;
const E20 = new Dec(1n, 20);

/**
 * Display rules recovered from Calculator 12.0: ≤ 8 fraction digits, rounded;
 * integers below 1e20 in full with grouping; ≥ 1e20 or < 1e-8 in e-notation.
 */
export class NumberFormat {
  constructor({ grouping = true, places = null, group = LOCALE_PARTS.group, decimal = LOCALE_PARTS.decimal } = {}) {
    this.grouping = grouping;
    this.places = places;       // null = automatic
    this.groupSep = group;
    this.decimalSep = decimal;
  }

  format(value) {
    const v = Dec.from(value);
    if (v.isZero) return this.places > 0 ? `0${this.decimalSep}${'0'.repeat(this.places)}` : '0';
    const rounded = v.round(this.places ?? MAX_FRACTION_DIGITS);
    if (!v.abs().lt(E20) || rounded.isZero) return this.scientific(v);
    return this.plain(rounded);
  }

  plain(v) {
    let text = v.toPlain();
    const neg = text.startsWith('-');
    if (neg) text = text.slice(1);
    let [int, frac = ''] = text.split('.');
    if (this.places !== null) frac = frac.padEnd(this.places, '0');
    else frac = frac.replace(/0+$/, '');
    let out = (neg ? '-' : '') + this.group(int || '0');
    if (frac) out += this.decimalSep + frac;
    return out;
  }

  scientific(v) {
    const neg = v.sign < 0;
    const m = (neg ? -v.m : v.m).toString();
    let exponent = m.length - 1 + v.e;
    let mantissa = new Dec(BigInt(m), -(m.length - 1)).round(SCI_DIGITS - 1);
    if (!mantissa.lt(10)) { mantissa = mantissa.div(10); exponent += 1; }
    let text = mantissa.toPlain();
    if (text.includes('.')) text = text.replace(/0+$/, '').replace(/\.$/, '');
    return `${neg ? '-' : ''}${text.replace('.', this.decimalSep)}e${exponent}`;
  }

  group(int) {
    if (!this.grouping || int.length <= 3) return int;
    let out = '';
    for (let i = 0; i < int.length; i++) {
      if (i > 0 && (int.length - i) % 3 === 0) out += this.groupSep;
      out += int[i];
    }
    return out;
  }

  /** A number exactly as typed (keeps `1.50` and a trailing point), plus grouping. */
  typed(text) {
    const neg = text.startsWith('-');
    const [int, frac] = (neg ? text.slice(1) : text).split('.');
    let out = (neg ? '-' : '') + this.group(int || '0');
    if (frac !== undefined) out += this.decimalSep + frac;
    return out;
  }
}

// ── Rendering ───────────────────────────────────────────────────────────

/**
 * Turns an expression into display spans `{ text, level, italic }`:
 * level > 0 superscript, < 0 subscript. `sin(30)`, `√(2)`, `2¹⁰`, `41₁₆+1₁₆`.
 */
export function render(tokens, format, { showsBase = false } = {}) {
  const node = parse(tokens);
  if (!node) return [];
  const out = [];
  const text = (s, level, italic = false) => out.push({ text: s, level, italic });

  function emit(n, level) {
    if (!n) return;
    const sub = (m, l = level) => emit(m, l);
    const wrapped = (inner, closed) => { text('(', level); sub(inner); if (closed) text(')', level); };
    const operand = (inner, closed) => {
      if (inner && inner.k === 'group') wrapped(inner.inner, inner.closed); else wrapped(inner, closed);
    };
    const exponent = (inner, closed) => {
      if (!inner) { text('x', level + 1); return; }
      if (inner.k === 'num' || inner.k === 'const' || inner.k === 'post') { emit(inner, level + 1); return; }
      text('(', level + 1); emit(inner, level + 1); if (closed) text(')', level + 1);
    };
    switch (n.k) {
      case 'empty': return;
      case 'num':
        text(n.base === 10 ? format.typed(n.text) : n.text.toUpperCase(), level);
        if (showsBase) text(String(n.base), level - 1);
        return;
      case 'const':
        if (n.c === 'pi') text('π', level);
        else if (n.c === 'e') text('e', level, true);
        else text(format.format(n.c), level);
        return;
      case 'group': wrapped(n.inner, n.closed); return;
      case 'post':
        sub(n.x);
        if (n.op === 'sq') text('2', level + 1);
        else if (n.op === 'cube') text('3', level + 1);
        else text(n.op === 'fact' ? '!' : '%', level);
        return;
      case 'bin':
        switch (n.op) {
          case 'pow': sub(n.l); if (n.r) sub(n.r, level + 1); else text('y', level + 1); return;
          case 'rpow': if (n.r) sub(n.r); else text('y', level); sub(n.l, level + 1); return;
          case 'root':
            if (n.r) sub(n.r, level + 1); else text('y', level + 1);
            text('√', level);
            if (n.l.k === 'group') sub(n.l); else { text('(', level); sub(n.l); text(')', level); }
            return;
          case 'logy':
            text('log', level);
            if (n.r) sub(n.r, level - 1); else text('y', level - 1);
            if (n.l.k === 'group') sub(n.l); else { text('(', level); sub(n.l); text(')', level); }
            return;
          default: sub(n.l); text(SYMBOL[n.op] ?? '?', level); sub(n.r);
        }
        return;
      case 'pre': {
        const { fn, inner, closed } = n;
        switch (fn) {
          case 'exp': text('e', level, true); exponent(inner, closed); return;
          case 'tenPow': text('10', level); exponent(inner, closed); return;
          case 'twoPow': text('2', level); exponent(inner, closed); return;
          case 'sqrt': text('√', level); operand(inner, closed); return;
          case 'cbrt': text('3', level + 1); text('√', level); operand(inner, closed); return;
          case 'recip': text('1/', level); operand(inner, closed); return;
          case 'neg': text('-', level); operand(inner, closed); return;
          case 'twosNeg': text('NEG', level); operand(inner, closed); return;
          case 'log10': text('log', level); text('10', level - 1); operand(inner, closed); return;
          case 'log2': text('log', level); text('2', level - 1); operand(inner, closed); return;
          case 'asin': case 'acos': case 'atan': case 'asinh': case 'acosh': case 'atanh':
            text(fn.slice(1), level); text('-1', level + 1); operand(inner, closed); return;
          case 'not': text('NOT', level); operand(inner, closed); return;
          case 'rol': text('RoL', level); operand(inner, closed); return;
          case 'ror': text('RoR', level); operand(inner, closed); return;
          case 'flip8': text('flip', level); text('8', level - 1); operand(inner, closed); return;
          case 'flip16': text('flip', level); text('16', level - 1); operand(inner, closed); return;
          default: text(fn, level); operand(inner, closed);
        }
      }
    }
  }

  emit(node, 0);
  // Merge neighbouring spans that share a style.
  const merged = [];
  for (const s of out) {
    if (!s.text) continue;
    const last = merged[merged.length - 1];
    if (last && last.level === s.level && last.italic === s.italic) last.text += s.text;
    else merged.push({ ...s });
  }
  return merged;
}

export const plainText = (spans) => spans.map(s => s.text).join('');

// ── Expression calculator ───────────────────────────────────────────────

const MAX_DIGITS = 20;

function depth(tokens) {
  let d = 0;
  for (const t of tokens) {
    if (t.t === 'open') d++;
    if (t.t === 'close' && d > 0) d--;
  }
  return d;
}

/** Expression entry used by Basic, Scientific and Programmer modes. */
export class AlgebraicCalculator {
  constructor(kind = 'decimal') {
    this.kind = kind;            // 'decimal' | 'programmer'
    this.angle = 'deg';
    this.base = 10;
    this.tokens = [];
    this.evaluated = null;       // tokens shown above a result after `=`
    this.result = null;          // Dec
    this.intResult = null;       // BigInt (programmer)
    this.error = null;           // CalcError
    this.repeatOp = null;
    this.repeatOperand = [];
  }

  get showingResult() { return this.evaluated !== null; }
  get showsAllClear() { return this.tokens.length === 0 || this.showingResult; }
  get numberBase() { return this.kind === 'programmer' ? this.base : 10; }

  inputDigit(d) {
    const digit = d.toUpperCase();
    if (this.kind === 'programmer') {
      const v = parseInt(digit, 16);
      if (Number.isNaN(v) || v >= this.base) return;
    }
    this._begin(false);
    const last = this.tokens[this.tokens.length - 1];
    if (last && last.t === 'num') {
      let text = last.text;
      if (text.replace(/[^0-9A-F]/gi, '').length >= MAX_DIGITS) return;
      if (text === '0') text = digit;
      else if (text === '-0') text = `-${digit}`;
      else text += digit;
      if (this.kind === 'programmer' && this._overflows(text, last.base)) return;
      this.tokens[this.tokens.length - 1] = T.num(text, last.base);
    } else {
      this._implicitMultiply();
      this.tokens.push(T.num(digit, this.numberBase));
    }
  }

  inputPoint() {
    if (this.kind !== 'decimal') return;
    this._begin(false);
    const last = this.tokens[this.tokens.length - 1];
    if (last && last.t === 'num') {
      if (last.text.includes('.')) return;
      this.tokens[this.tokens.length - 1] = T.num((last.text === '-' ? '-0' : last.text) + '.', last.base);
    } else {
      this._implicitMultiply();
      this.tokens.push(T.num('0.', 10));
    }
  }

  inputOperator(op) {
    this._begin(true);
    const last = this.tokens[this.tokens.length - 1];
    if (!last) {
      this.tokens = op === 'sub' ? [T.num('-', this.numberBase)] : [T.num('0', this.numberBase), T.bin(op)];
      return;
    }
    if (last.t === 'bin') { this.tokens[this.tokens.length - 1] = T.bin(op); return; }   // `2+×3` → `2×3`
    if (last.t === 'open' || last.t === 'pre') { if (op === 'sub') this.tokens.push(T.num('-', this.numberBase)); return; }
    if (last.t === 'num' && last.text === '-') return;
    this.tokens.push(T.bin(op));
  }

  openParen() {
    this._begin(false);
    this._implicitMultiply();
    this.tokens.push(T.open());
  }

  closeParen() {
    const last = this.tokens[this.tokens.length - 1];
    if (this.showingResult || depth(this.tokens) === 0 || !endsOperand(last)) return;
    this.tokens.push(T.close());
  }

  /** Wraps the last operand (`30` → `sin(30)`), or opens `sin(` when there is none. */
  applyFunction(fn) {
    this._begin(true);
    const range = this._lastOperandRange();
    if (range) {
      const [start, end] = range;
      if (this.tokens[start].t === 'open') this.tokens.splice(start, 0, T.pre(fn));
      else {
        this.tokens.splice(end, 0, T.close());
        this.tokens.splice(start, 0, T.pre(fn), T.open());
      }
    } else {
      this._implicitMultiply();
      this.tokens.push(T.pre(fn), T.open());
    }
  }

  applyPostfix(op) {
    this._begin(true);
    const last = this.tokens[this.tokens.length - 1];
    if (!endsOperand(last)) return;
    if (op === 'pct' && last.t === 'post' && last.op === 'pct') return;
    this.tokens.push(T.post(op));
  }

  /** Programmer `<<` / `>>`: shift the last operand by one bit, shown as `(x<<1)`. */
  shiftByOne(left) {
    this._begin(true);
    const range = this._lastOperandRange();
    if (!range) return;
    this.tokens.splice(range[1], 0, T.bin(left ? 'shl' : 'shr'), T.num('1', 10), T.close());
    this.tokens.splice(range[0], 0, T.open());
  }

  inputConstant(c) {
    this._begin(false);
    this._implicitMultiply();
    this.tokens.push(T.constant(c));
  }

  /** Inserts a value (memory recall, history, paste). */
  inputValue(v) {
    const dec = Dec.from(v);
    if (this.kind === 'programmer') {
      this._begin(false);
      this._implicitMultiply();
      this.tokens.push(T.num(integerString(BigInt.asIntN(64, dec.trunc().toBigInt()), this.base), this.base));
    } else {
      this.inputConstant(dec);
    }
  }

  toggleSign() {
    this._begin(true);
    const last = this.tokens[this.tokens.length - 1];
    if (last && last.t === 'num') {
      const text = last.text.startsWith('-') ? last.text.slice(1) : `-${last.text}`;
      if (text === '') this.tokens.pop(); else this.tokens[this.tokens.length - 1] = T.num(text, last.base);
    } else if (last && last.t === 'const' && last.c instanceof Dec) {
      this.tokens[this.tokens.length - 1] = T.constant(last.c.neg());
    } else if (this._lastOperandRange()) {
      this.applyFunction('neg');
    }
    // Observed: ± with no operand does nothing.
  }

  backspace() {
    if (this.showingResult) { this.clearAll(); return; }
    this.error = null;
    const last = this.tokens[this.tokens.length - 1];
    if (!last) return;
    if (last.t === 'num') {
      const text = last.text.slice(0, -1);
      if (text === '' || text === '-') this.tokens.pop(); else this.tokens[this.tokens.length - 1] = T.num(text, last.base);
    } else if (last.t === 'open') {
      this.tokens.pop();
      if (this.tokens[this.tokens.length - 1]?.t === 'pre') this.tokens.pop();
    } else {
      this.tokens.pop();
    }
  }

  /** `C` clears the input; `AC` (shown when already clear) also forgets the repeat operation. */
  clear() {
    if (this.showsAllClear) this.clearAll();
    else { this.tokens = []; this.error = null; }
  }

  clearAll() {
    this.tokens = [];
    this.evaluated = null;
    this.result = null;
    this.intResult = null;
    this.error = null;
    this.repeatOp = null;
    this.repeatOperand = [];
  }

  /** Evaluates; returns `{ tokens, value }` for history, or null. */
  equals() {
    let expr = this.tokens.slice();
    if (this.showingResult) {
      const ans = this.currentValue;
      if (!this.repeatOp || ans === null) return null;
      expr = [this._answerToken(ans), T.bin(this.repeatOp), ...this.repeatOperand];
    } else {
      if (!expr.length) return null;
      if (expr[expr.length - 1].t === 'bin') return null;          // observed: `5+=` does nothing
      if (expr[expr.length - 1].t === 'open') {
        expr.pop();
        if (expr[expr.length - 1]?.t === 'pre') expr.pop();
      }
      if (!expr.length) return null;
      for (let k = depth(expr); k > 0; k--) expr.push(T.close());
      this._captureRepeat(expr);
    }
    try {
      const value = this._evaluate(expr, true);
      this.evaluated = expr;
      this.tokens = [];
      this.error = null;
      return { tokens: expr, value };
    } catch (e) {
      if (!(e instanceof CalcError) && !(e instanceof RangeError)) throw e;
      this.evaluated = expr;
      this.tokens = [];
      this.result = null;
      this.intResult = null;
      this.error = e instanceof CalcError ? e : undefinedError();
      return null;
    }
  }

  /** Value of the expression typed so far (live converter, bit grid). */
  get currentValue() {
    if (this.showingResult) return this.kind === 'programmer' ? (this.intResult === null ? null : new Dec(this.intResult)) : this.result;
    if (!this.tokens.length) return this.result;
    const expr = this.tokens.slice();
    while (expr.length && expr[expr.length - 1].t === 'bin') expr.pop();
    for (let k = depth(expr); k > 0; k--) expr.push(T.close());
    try { return this._evaluate(expr, false); } catch (_) { return null; }
  }

  /** The integer being typed (Programmer bit grid). */
  get currentOperandInt() {
    const last = this.tokens[this.tokens.length - 1];
    if (last && last.t === 'num') return BigInt.asIntN(64, parseNumber(last.text, last.base).trunc().toBigInt());
    if (this.showingResult) return this.intResult ?? 0n;
    if (!this.tokens.length) return this.intResult ?? 0n;
    const v = this.currentValue;
    return v ? BigInt.asIntN(64, v.trunc().toBigInt()) : 0n;
  }

  setCurrentOperand(v) {
    const text = integerString(v, this.base);
    const last = this.tokens[this.tokens.length - 1];
    if (last && last.t === 'num' && !this.showingResult) this.tokens[this.tokens.length - 1] = T.num(text, this.base);
    else {
      this._begin(false);
      this._implicitMultiply();
      this.tokens.push(T.num(text, this.base));
    }
  }

  convertBase(newBase) {
    this.base = newBase;
    this.tokens = this.tokens.map(t => {
      if (t.t !== 'num' || t.base === newBase) return t;
      return T.num(integerString(BigInt.asIntN(64, parseIntBig(t.text, t.base)), newBase), newBase);
    });
  }

  // internals

  _answerToken(v) {
    return this.kind === 'programmer'
      ? T.num(integerString(BigInt.asIntN(64, v.trunc().toBigInt()), this.base), this.base)
      : T.constant(v);
  }

  /** After a result, operators continue from it and everything else starts fresh. */
  _begin(continuing) {
    if (!this.showingResult) { this.error = null; return; }
    const ans = this.error ? null : this.currentValue;
    this.evaluated = null;
    this.error = null;
    this.tokens = continuing && ans !== null ? [this._answerToken(ans)] : [];
  }

  _implicitMultiply() {
    if (endsOperand(this.tokens[this.tokens.length - 1])) this.tokens.push(T.bin('mul'));
  }

  _evaluate(expr, store) {
    const node = parse(expr);
    if (!node) return ZERO;
    if (this.kind === 'programmer') {
      const v = evaluateInt(node);
      if (store) { this.intResult = v; this.result = new Dec(v); }
      return new Dec(v);
    }
    const v = new Evaluator(this.angle).evaluate(node);
    if (store) this.result = v;
    return v;
  }

  _captureRepeat(expr) {
    let d = 0;
    let lastIndex = -1;
    expr.forEach((t, i) => {
      if (t.t === 'open') d++;
      else if (t.t === 'close') d--;
      else if (t.t === 'bin' && d === 0) lastIndex = i;
    });
    if (lastIndex >= 0 && lastIndex + 1 < expr.length) {
      this.repeatOp = expr[lastIndex].op;
      this.repeatOperand = expr.slice(lastIndex + 1);
    } else {
      this.repeatOp = null;
      this.repeatOperand = [];
    }
  }

  /** [start, end) of the last complete operand, including a prefix function and trailing postfixes. */
  _lastOperandRange() {
    const toks = this.tokens;
    if (!endsOperand(toks[toks.length - 1])) return null;
    let i = toks.length - 1;
    while (i >= 0 && toks[i].t === 'post') i--;
    if (i < 0) return null;
    if (toks[i].t === 'close') {
      let d = 0;
      while (i >= 0) {
        if (toks[i].t === 'close') d++;
        if (toks[i].t === 'open') { d--; if (d === 0) break; }
        i--;
      }
      if (i > 0 && toks[i - 1].t === 'pre') i--;
    } else if (toks[i].t !== 'num' && toks[i].t !== 'const') {
      return null;
    }
    return [Math.max(i, 0), toks.length];
  }

  _overflows(text, base) {
    const digits = text.startsWith('-') ? text.slice(1) : text;
    return parseIntBig(digits, base) > (base === 10 ? (1n << 63n) - 1n : (1n << 64n) - 1n);
  }
}

// ── RPN ─────────────────────────────────────────────────────────────────

/**
 * Reverse Polish stack (View ▸ RPN Mode). Observed: `3 enter 4 enter 5`
 * shows rows 3 / 4 / 5 with 5 still being typed.
 */
export class RPNCalculator {
  constructor() {
    this.stack = [];
    this.input = '';
    this.error = null;
    this.angle = 'deg';
  }

  get rows() {
    const r = this.stack.map(v => ({ kind: 'value', value: v }));
    if (this.input) r.push({ kind: 'typing', text: this.input });
    if (this.error) r.push({ kind: 'error', error: this.error });
    return r;
  }

  get showsAllClear() { return this.input === ''; }
  get x() { return this.input ? parseNumber(this.input) : (this.stack[this.stack.length - 1] ?? null); }

  inputDigit(d) {
    this.error = null;
    if (this.input.replace(/\D/g, '').length >= MAX_DIGITS) return;
    if (this.input === '0') this.input = d;
    else if (this.input === '-0') this.input = `-${d}`;
    else this.input += d;
  }

  inputPoint() {
    this.error = null;
    if (!this.input) this.input = '0.';
    else if (!this.input.includes('.')) this.input += '.';
  }

  toggleSign() {
    if (this.input) this.input = this.input.startsWith('-') ? this.input.slice(1) : `-${this.input}`;
    else if (this.stack.length) this.stack.push(this.stack.pop().neg());
  }

  backspace() {
    if (this.input) { this.input = this.input.slice(0, -1); if (this.input === '-') this.input = ''; }
    else this.error = null;
  }

  /** Pushes the typed value; with nothing typed, duplicates x. */
  enter() {
    this.error = null;
    if (this.input) { this.stack.push(parseNumber(this.input)); this.input = ''; }
    else if (this.stack.length) this.stack.push(this.stack[this.stack.length - 1]);
  }

  clear() {
    if (!this.input) this.stack = [];
    this.input = '';
    this.error = null;
  }

  push(v) { this._commit(); this.stack.push(Dec.from(v)); }

  /** y op x: the scientific keys become yˣ and ˣ√y. */
  binary(op) {
    this._commit();
    if (this.stack.length < 2) return;
    const x = this.stack.pop();
    const y = this.stack.pop();
    this._run(() => new Evaluator(this.angle).binary(op, y, x), () => this.stack.push(y, x));
  }

  unary(fn) {
    this._commit();
    if (!this.stack.length) return;
    const x = this.stack.pop();
    this._run(() => new Evaluator(this.angle).apply(fn, x), () => this.stack.push(x));
  }

  postfix(op) {
    this._commit();
    if (!this.stack.length) return;
    const x = this.stack.pop();
    if (op === 'pct' && this.stack.length) { this.stack.push(this.stack[this.stack.length - 1].mul(x).div(100)); return; }
    this._run(() => new Evaluator(this.angle).evaluate({ k: 'post', op, x: { k: 'const', c: x } }), () => this.stack.push(x));
  }

  swap() {
    this._commit();
    const n = this.stack.length;
    if (n >= 2) [this.stack[n - 1], this.stack[n - 2]] = [this.stack[n - 2], this.stack[n - 1]];
  }

  /** R↓: x moves to the top of the stack. */
  rollDown() { this._commit(); if (this.stack.length >= 2) this.stack.unshift(this.stack.pop()); }
  /** R↑: the top of the stack moves to x. */
  rollUp() { this._commit(); if (this.stack.length >= 2) this.stack.push(this.stack.shift()); }

  drop() {
    if (this.input) { this.input = ''; return; }
    this.stack.pop();
  }

  _commit() {
    this.error = null;
    if (this.input) { this.stack.push(parseNumber(this.input)); this.input = ''; }
  }

  _run(fn, restore) {
    try { this.stack.push(fn()); } catch (e) {
      if (!(e instanceof CalcError) && !(e instanceof RangeError)) throw e;
      restore();
      this.error = e instanceof CalcError ? e : undefinedError();
    }
  }
}
