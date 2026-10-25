//! Exact decimal numbers.
//!
//! macOS Calculator does its arithmetic in decimal (0.1+0.2 = 0.3, 2÷3×3 = 2,
//! 20-digit integers stay exact), so this engine does too. A value is
//! `m × 10^e` with an arbitrary-size integer mantissa, kept to 38 significant
//! digits like Foundation's `Decimal`. Transcendental functions go through `f64`.

use num_bigint::BigInt;
use num_integer::Integer;
use num_traits::{Signed, ToPrimitive, Zero};
use std::cmp::Ordering;

pub const PRECISION: usize = 38;

fn pow10(n: u32) -> BigInt {
    BigInt::from(10u8).pow(n)
}

fn digits(m: &BigInt) -> usize {
    if m.is_zero() {
        return 1;
    }
    if let Some(v) = m.to_i128() {
        return v.unsigned_abs().checked_ilog10().unwrap_or(0) as usize + 1;
    }
    m.abs().to_string().len()
}

#[derive(Clone, Debug)]
pub struct Dec {
    m: BigInt,
    e: i32,
}

impl PartialEq for Dec {
    fn eq(&self, other: &Self) -> bool {
        self.cmp_dec(other) == Ordering::Equal
    }
}

impl Dec {
    pub fn new(m: BigInt, e: i32) -> Dec {
        let mut d = Dec { m, e };
        d.normalize();
        d
    }

    pub fn zero() -> Dec {
        Dec { m: BigInt::zero(), e: 0 }
    }

    pub fn from_i64(v: i64) -> Dec {
        Dec::new(BigInt::from(v), 0)
    }

    pub fn from_bigint(v: BigInt) -> Dec {
        Dec::new(v, 0)
    }

    fn normalize(&mut self) {
        if self.m.is_zero() {
            self.e = 0;
            return;
        }
        // Fast path: anything under 2^126 has at most 38 digits and fits an i128,
        // so trailing zeros come off with native arithmetic (no big-number text).
        if self.m.bits() <= 126 {
            if let Some(mut v) = self.m.to_i128() {
                if v.unsigned_abs() < 10u128.pow(PRECISION as u32) {
                    while v % 10 == 0 {
                        v /= 10;
                        self.e += 1;
                    }
                    self.m = BigInt::from(v);
                    return;
                }
            }
        }
        let n = digits(&self.m);
        if n > PRECISION {
            // Round half away from zero to PRECISION significant digits.
            let extra = (n - PRECISION) as u32;
            let p = pow10(extra);
            let neg = self.m.is_negative();
            let a = self.m.abs();
            let (mut q, r) = a.div_rem(&p);
            if r * 2 >= p {
                q += 1;
            }
            self.m = if neg { -q } else { q };
            self.e += extra as i32;
        }
        let ten = BigInt::from(10u8);
        while !self.m.is_zero() && (&self.m % &ten).is_zero() {
            self.m /= &ten;
            self.e += 1;
        }
    }

    /// Parses `-12.5`, `.5`, `1e-12`. None for anything else.
    pub fn parse(text: &str) -> Option<Dec> {
        let s = text.trim();
        let (neg, rest) = match s.strip_prefix('-') {
            Some(r) => (true, r),
            None => (false, s.strip_prefix('+').unwrap_or(s)),
        };
        let (num, exp) = match rest.find(['e', 'E']) {
            Some(i) => (&rest[..i], rest[i + 1..].parse::<i32>().ok()?),
            None => (rest, 0),
        };
        let (int, frac) = match num.find('.') {
            Some(i) => (&num[..i], &num[i + 1..]),
            None => (num, ""),
        };
        if int.is_empty() && frac.is_empty() {
            return None;
        }
        if !int.bytes().all(|b| b.is_ascii_digit()) || !frac.bytes().all(|b| b.is_ascii_digit()) {
            return None;
        }
        let joined = format!("{}{}", if int.is_empty() { "0" } else { int }, frac);
        let mut m: BigInt = joined.parse().ok()?;
        if neg {
            m = -m;
        }
        Some(Dec::new(m, exp - frac.len() as i32))
    }

    /// Shortest round-trip form, so 0.5 stays 0.5 rather than 0.50000000000000001.
    pub fn from_f64(v: f64) -> Option<Dec> {
        if !v.is_finite() {
            return None;
        }
        Dec::parse(&format!("{}", v))
    }

    pub fn is_zero(&self) -> bool {
        self.m.is_zero()
    }
    pub fn sign(&self) -> i32 {
        if self.m.is_negative() {
            -1
        } else if self.m.is_zero() {
            0
        } else {
            1
        }
    }
    pub fn is_integer(&self) -> bool {
        self.e >= 0
    }
    /// Mantissa ±1: an exact power of ten.
    pub fn is_power_of_ten(&self) -> Option<i32> {
        if self.m == BigInt::from(1) {
            Some(self.e)
        } else {
            None
        }
    }

    pub fn neg(&self) -> Dec {
        Dec { m: -self.m.clone(), e: self.e }
    }
    pub fn abs(&self) -> Dec {
        Dec { m: self.m.abs(), e: self.e }
    }

    fn align(a: &Dec, b: &Dec) -> (BigInt, BigInt, i32) {
        let e = a.e.min(b.e);
        (
            &a.m * pow10((a.e - e) as u32),
            &b.m * pow10((b.e - e) as u32),
            e,
        )
    }

    pub fn add(&self, o: &Dec) -> Dec {
        let (x, y, e) = Dec::align(self, o);
        Dec::new(x + y, e)
    }
    pub fn sub(&self, o: &Dec) -> Dec {
        let (x, y, e) = Dec::align(self, o);
        Dec::new(x - y, e)
    }
    pub fn mul(&self, o: &Dec) -> Dec {
        Dec::new(&self.m * &o.m, self.e + o.e)
    }

    /// None on division by zero.
    pub fn div(&self, o: &Dec) -> Option<Dec> {
        if o.is_zero() {
            return None;
        }
        if self.is_zero() {
            return Some(Dec::zero());
        }
        // Scale the dividend so the quotient carries PRECISION + 2 digits, then round.
        let k = (PRECISION as i64 + 2 + digits(&o.m) as i64 - digits(&self.m) as i64).max(0) as u32;
        Some(Dec::new(
            (&self.m * pow10(k)) / &o.m,
            self.e - o.e - k as i32,
        ))
    }

    pub fn cmp_dec(&self, o: &Dec) -> Ordering {
        let (x, y, _) = Dec::align(self, o);
        x.cmp(&y)
    }
    pub fn lt(&self, o: &Dec) -> bool {
        self.cmp_dec(o) == Ordering::Less
    }
    pub fn eq_i64(&self, v: i64) -> bool {
        *self == Dec::from_i64(v)
    }

    /// Round to `scale` fraction digits, half away from zero.
    pub fn round(&self, scale: u32) -> Dec {
        if -(self.e as i64) <= scale as i64 {
            return self.clone();
        }
        let drop = (-(self.e as i64) - scale as i64) as u32;
        if drop as usize > digits(&self.m) + 1 {
            return Dec::zero();
        }
        let p = pow10(drop);
        let neg = self.m.is_negative();
        let a = self.m.abs();
        let (mut q, r) = a.div_rem(&p);
        if r * 2 >= p {
            q += 1;
        }
        Dec::new(if neg { -q } else { q }, -(scale as i32))
    }

    /// Integer part toward zero.
    pub fn trunc(&self) -> Dec {
        if self.e >= 0 {
            return self.clone();
        }
        Dec::new(&self.m / pow10((-self.e) as u32), 0)
    }

    pub fn floor(&self) -> Dec {
        let t = self.trunc();
        if self.sign() < 0 && t != *self {
            t.sub(&Dec::from_i64(1))
        } else {
            t
        }
    }

    /// Integer power by repeated squaring (negative exponents divide).
    pub fn pow_int(&self, n: i64) -> Option<Dec> {
        if n < 0 {
            return Dec::from_i64(1).div(&self.pow_int(-n)?);
        }
        let mut result = Dec::from_i64(1);
        let mut base = self.clone();
        let mut k = n;
        while k > 0 {
            if k & 1 == 1 {
                result = result.mul(&base);
            }
            base = base.mul(&base);
            k >>= 1;
        }
        Some(result)
    }

    /// Exact integer as i64 when small, else None.
    pub fn to_small_int(&self) -> Option<i64> {
        if !self.is_integer() || self.e > 18 {
            return None;
        }
        let v = &self.m * pow10(self.e as u32);
        v.to_i64().filter(|x| x.abs() < 9_007_199_254_740_991)
    }

    pub fn to_bigint(&self) -> BigInt {
        if self.e >= 0 {
            &self.m * pow10(self.e as u32)
        } else {
            &self.m / pow10((-self.e) as u32)
        }
    }

    /// Two's-complement 64-bit view of the integer part (BigInt.asIntN(64)).
    pub fn to_i64_wrapping(&self) -> i64 {
        wrap_i64(&self.to_bigint())
    }

    pub fn to_f64(&self) -> f64 {
        self.to_plain().parse::<f64>().unwrap_or(f64::NAN)
    }

    /// Mantissa digits and decimal exponent of the leading digit (for e-notation).
    pub fn sci_parts(&self) -> (String, i32) {
        let m = self.m.abs().to_string();
        let exp = m.len() as i32 - 1 + self.e;
        (m, exp)
    }

    /// Plain digits with no exponent: `-1234.5`, `0.000000000001`.
    pub fn to_plain(&self) -> String {
        let neg = self.m.is_negative();
        let mut s = self.m.abs().to_string();
        if self.e >= 0 {
            s.push_str(&"0".repeat(self.e as usize));
        } else {
            let point = s.len() as i64 + self.e as i64;
            s = if point > 0 {
                format!("{}.{}", &s[..point as usize], &s[point as usize..])
            } else {
                format!("0.{}{}", "0".repeat((-point) as usize), s)
            };
        }
        if neg {
            format!("-{}", s)
        } else {
            s
        }
    }
}

/// Reduce any integer to i64 the way 64-bit hardware does.
pub fn wrap_i64(v: &BigInt) -> i64 {
    let modulus = BigInt::from(1u8) << 64;
    let r = v.mod_floor(&modulus);
    r.to_u64().unwrap_or(0) as i64
}

pub fn pi() -> Dec {
    Dec::parse("3.14159265358979323846264338327950288").unwrap()
}
pub fn e() -> Dec {
    Dec::parse("2.71828182845904523536028747135266250").unwrap()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn exact_decimal_arithmetic() {
        let a = Dec::parse("0.1").unwrap();
        let b = Dec::parse("0.2").unwrap();
        assert_eq!(a.add(&b).to_plain(), "0.3");
        let third = Dec::from_i64(1).div(&Dec::from_i64(3)).unwrap();
        assert_eq!(third.mul(&Dec::from_i64(3)).round(10).to_plain(), "1");
        assert_eq!(Dec::parse("1e-12").unwrap().to_plain(), "0.000000000001");
        assert_eq!(Dec::parse("-12.50").unwrap().to_plain(), "-12.5");
        assert_eq!(Dec::parse("2.5").unwrap().round(0).to_plain(), "3");
        assert_eq!(Dec::parse("-2.5").unwrap().floor().to_plain(), "-3");
        assert_eq!(Dec::from_i64(2).pow_int(10).unwrap().to_plain(), "1024");
        assert_eq!(Dec::from_i64(-1).to_i64_wrapping(), -1);
        assert_eq!(Dec::from_f64(0.5).unwrap().to_plain(), "0.5");
    }
}
