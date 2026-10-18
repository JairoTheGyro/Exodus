/**
 * Calculator — exact decimal numbers.
 *
 * macOS Calculator does its arithmetic in decimal (0.1+0.2 = 0.3, 2÷3×3 = 2,
 * 20-digit integers stay exact), so the Exodus port does too. A value is
 * `m × 10^e` with a BigInt mantissa, kept to 38 significant digits like
 * Foundation's `Decimal`. Transcendental functions go through `Number`.
 */

export const PRECISION = 38;
const TEN = 10n;

function digits(m) {
  return (m < 0n ? -m : m).toString().length;
}

function pow10(n) {
  return TEN ** BigInt(n);
}

export class Dec {
  constructor(m, e = 0) {
    this.m = m;
    this.e = e;
    this._normalize();
  }

  _normalize() {
    if (this.m === 0n) { this.e = 0; return; }
    const extra = digits(this.m) - PRECISION;
    if (extra > 0) {
      // Round half away from zero to PRECISION significant digits.
      const p = pow10(extra);
      const neg = this.m < 0n;
      let a = neg ? -this.m : this.m;
      let q = a / p;
      if ((a % p) * 2n >= p) q += 1n;
      this.m = neg ? -q : q;
      this.e += extra;
    }
    while (this.m !== 0n && this.m % TEN === 0n) { this.m /= TEN; this.e += 1; }
  }

  static from(x) {
    if (x instanceof Dec) return x;
    if (typeof x === 'bigint') return new Dec(x, 0);
    if (typeof x === 'number') return Dec.fromNumber(x);
    return Dec.parse(String(x));
  }

  /** Parses `-12.5`, `.5`, `1e-12`. Returns null for anything else. */
  static parse(text) {
    const s = String(text).trim();
    const m = /^([+-]?)(\d*)(?:\.(\d*))?(?:[eE]([+-]?\d+))?$/.exec(s);
    if (!m || (m[2] === '' && (m[3] ?? '') === '')) return null;
    const frac = m[3] ?? '';
    const mant = BigInt((m[2] || '0') + frac) * (m[1] === '-' ? -1n : 1n);
    return new Dec(mant, (m[4] ? parseInt(m[4], 10) : 0) - frac.length);
  }

  /** Shortest round-trip form, so 0.5 stays 0.5 rather than 0.50000000000000001. */
  static fromNumber(n) {
    if (!Number.isFinite(n)) throw new RangeError('non-finite');
    return Dec.parse(String(n));
  }

  get isZero() { return this.m === 0n; }
  get sign() { return this.m < 0n ? -1 : this.m > 0n ? 1 : 0; }
  get isInteger() { return this.e >= 0; }

  neg() { return new Dec(-this.m, this.e); }
  abs() { return this.m < 0n ? this.neg() : this; }

  static _align(a, b) {
    const e = Math.min(a.e, b.e);
    return [a.m * pow10(a.e - e), b.m * pow10(b.e - e), e];
  }

  add(o) { o = Dec.from(o); const [x, y, e] = Dec._align(this, o); return new Dec(x + y, e); }
  sub(o) { o = Dec.from(o); const [x, y, e] = Dec._align(this, o); return new Dec(x - y, e); }
  mul(o) { o = Dec.from(o); return new Dec(this.m * o.m, this.e + o.e); }

  div(o) {
    o = Dec.from(o);
    if (o.isZero) throw new RangeError('division by zero');
    if (this.isZero) return new Dec(0n);
    // Scale the dividend so the quotient carries PRECISION + 2 digits, then round.
    const k = Math.max(0, PRECISION + 2 + digits(o.m) - digits(this.m));
    return new Dec((this.m * pow10(k)) / o.m, this.e - o.e - k);
  }

  cmp(o) {
    o = Dec.from(o);
    const [x, y] = Dec._align(this, o);
    return x < y ? -1 : x > y ? 1 : 0;
  }
  eq(o) { return this.cmp(o) === 0; }
  lt(o) { return this.cmp(o) < 0; }
  gt(o) { return this.cmp(o) > 0; }

  /** Round to `scale` fraction digits, half away from zero. */
  round(scale = 0) {
    if (-this.e <= scale) return this;
    const drop = -this.e - scale;
    if (drop > digits(this.m) + 1) return new Dec(0n);
    const p = pow10(drop);
    const neg = this.m < 0n;
    const a = neg ? -this.m : this.m;
    let q = a / p;
    if ((a % p) * 2n >= p) q += 1n;
    return new Dec(neg ? -q : q, -scale);
  }

  /** Integer part toward zero. */
  trunc() {
    if (this.e >= 0) return this;
    return new Dec(this.m / pow10(-this.e), 0);
  }

  floor() {
    const t = this.trunc();
    return (this.sign < 0 && !t.eq(this)) ? t.sub(1) : t;
  }

  /** Integer power by repeated squaring (negative exponents divide). */
  powInt(n) {
    if (n < 0) return new Dec(1n).div(this.powInt(-n));
    let result = new Dec(1n);
    let base = this;
    let k = n;
    while (k > 0) {
      if (k & 1) result = result.mul(base);
      base = base.mul(base);
      k >>= 1;
    }
    return result;
  }

  /** Exact integer as a JS number when small, else null. */
  toSafeInt() {
    if (!this.isInteger) return null;
    const v = this.m * pow10(this.e);
    return (v > BigInt(Number.MAX_SAFE_INTEGER) || v < -BigInt(Number.MAX_SAFE_INTEGER)) ? null : Number(v);
  }

  toBigInt() {
    return this.e >= 0 ? this.m * pow10(this.e) : this.m / pow10(-this.e);
  }

  toNumber() { return Number(this.toPlain()); }

  /** Plain digits with no exponent: `-1234.5`, `0.000000000001`. */
  toPlain() {
    const neg = this.m < 0n;
    let s = (neg ? -this.m : this.m).toString();
    if (this.e >= 0) s += '0'.repeat(this.e);
    else {
      const point = s.length + this.e;
      s = point > 0 ? `${s.slice(0, point)}.${s.slice(point)}` : `0.${'0'.repeat(-point)}${s}`;
    }
    return (neg ? '-' : '') + s;
  }

  toString() { return this.toPlain(); }
}

export const ZERO = new Dec(0n);
export const ONE = new Dec(1n);
export const PI = Dec.parse('3.14159265358979323846264338327950288');
export const E = Dec.parse('2.71828182845904523536028747135266250');
