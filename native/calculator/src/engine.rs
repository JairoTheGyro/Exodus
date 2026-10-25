//! Tokens, a tolerant parser and the two evaluators (exact decimal for
//! Basic/Scientific, 64-bit two's complement for Programmer).
//!
//! Behaviour reproduces probes of macOS Calculator 12.0, e.g. `12+3×4=` → 24,
//! `2+3%=` → 2.06 and `1÷0` → Undefined.

use crate::dec::{self, wrap_i64, Dec};
use num_bigint::BigInt;

// ── Tokens ──────────────────────────────────────────────────────────────

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Op {
    Add, Sub, Mul, Div, Mod,
    Pow, Rpow, Root, Logy, Ee,
    And, Or, Xor, Nor, Shl, Shr,
}

impl Op {
    pub fn parse(s: &str) -> Option<Op> {
        Some(match s {
            "add" => Op::Add, "sub" => Op::Sub, "mul" => Op::Mul, "div" => Op::Div, "mod" => Op::Mod,
            "pow" => Op::Pow, "rpow" => Op::Rpow, "root" => Op::Root, "logy" => Op::Logy, "ee" => Op::Ee,
            "and" => Op::And, "or" => Op::Or, "xor" => Op::Xor, "nor" => Op::Nor, "shl" => Op::Shl, "shr" => Op::Shr,
            _ => return None,
        })
    }

    /// Higher binds tighter.
    pub fn precedence(self) -> u8 {
        match self {
            Op::Or | Op::Xor | Op::Nor => 1,
            Op::And => 2,
            Op::Shl | Op::Shr => 3,
            Op::Add | Op::Sub => 4,
            Op::Mul | Op::Div | Op::Mod => 5,
            Op::Pow | Op::Rpow | Op::Root | Op::Logy | Op::Ee => 6,
        }
    }

    pub fn symbol(self) -> &'static str {
        match self {
            Op::Add => "+", Op::Sub => "−", Op::Mul => "×", Op::Div => "÷", Op::Ee => "E", Op::Mod => " mod ",
            Op::And => " AND ", Op::Or => " OR ", Op::Xor => " XOR ", Op::Nor => " NOR ",
            Op::Shl => "<<", Op::Shr => ">>",
            Op::Pow | Op::Rpow => "^", Op::Root => "√", Op::Logy => "log",
        }
    }
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Func {
    Sin, Cos, Tan, Asin, Acos, Atan, Sinh, Cosh, Tanh, Asinh, Acosh, Atanh,
    Sqrt, Cbrt, Ln, Log10, Log2, Exp, TenPow, TwoPow, Recip, Neg,
    Not, TwosNeg, Rol, Ror, Flip8, Flip16,
}

impl Func {
    pub fn parse(s: &str) -> Option<Func> {
        Some(match s {
            "sin" => Func::Sin, "cos" => Func::Cos, "tan" => Func::Tan,
            "asin" => Func::Asin, "acos" => Func::Acos, "atan" => Func::Atan,
            "sinh" => Func::Sinh, "cosh" => Func::Cosh, "tanh" => Func::Tanh,
            "asinh" => Func::Asinh, "acosh" => Func::Acosh, "atanh" => Func::Atanh,
            "sqrt" => Func::Sqrt, "cbrt" => Func::Cbrt, "ln" => Func::Ln, "log10" => Func::Log10, "log2" => Func::Log2,
            "exp" => Func::Exp, "tenPow" => Func::TenPow, "twoPow" => Func::TwoPow, "recip" => Func::Recip, "neg" => Func::Neg,
            "not" => Func::Not, "twosNeg" => Func::TwosNeg, "rol" => Func::Rol, "ror" => Func::Ror,
            "flip8" => Func::Flip8, "flip16" => Func::Flip16,
            _ => return None,
        })
    }

    pub fn name(self) -> &'static str {
        match self {
            Func::Sin => "sin", Func::Cos => "cos", Func::Tan => "tan",
            Func::Asin => "sin", Func::Acos => "cos", Func::Atan => "tan",
            Func::Sinh => "sinh", Func::Cosh => "cosh", Func::Tanh => "tanh",
            Func::Asinh => "sinh", Func::Acosh => "cosh", Func::Atanh => "tanh",
            Func::Sqrt => "√", Func::Cbrt => "√", Func::Ln => "ln", Func::Log10 => "log", Func::Log2 => "log",
            Func::Exp => "e", Func::TenPow => "10", Func::TwoPow => "2", Func::Recip => "1/", Func::Neg => "-",
            Func::Not => "NOT", Func::TwosNeg => "NEG", Func::Rol => "RoL", Func::Ror => "RoR",
            Func::Flip8 => "flip", Func::Flip16 => "flip",
        }
    }
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Post {
    Sq, Cube, Fact, Pct,
}

impl Post {
    pub fn parse(s: &str) -> Option<Post> {
        Some(match s {
            "sq" => Post::Sq, "cube" => Post::Cube, "fact" => Post::Fact, "pct" => Post::Pct,
            _ => return None,
        })
    }
}

#[derive(Clone, Debug, PartialEq)]
pub enum Constant {
    Pi,
    E,
    Value(Dec),
}

#[derive(Clone, Debug, PartialEq)]
pub enum Tok {
    Num(String, u32),
    Const(Constant),
    Bin(Op),
    Open,
    Close,
    /// Always followed by `Open`.
    Pre(Func),
    Post(Post),
}

impl Tok {
    pub fn ends_operand(&self) -> bool {
        matches!(self, Tok::Num(..) | Tok::Const(_) | Tok::Close | Tok::Post(_))
    }
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum CalcError {
    Undefined,
    Domain,
}

impl CalcError {
    pub fn message(self) -> &'static str {
        match self {
            CalcError::Undefined => "Undefined",
            CalcError::Domain => "Error",
        }
    }
}

pub type Calc<T> = Result<T, CalcError>;

// ── Parser ──────────────────────────────────────────────────────────────

#[derive(Clone, Debug)]
pub enum Node {
    Empty,
    Num(String, u32),
    Const(Constant),
    Bin(Op, Box<Node>, Option<Box<Node>>),
    Pre(Func, Option<Box<Node>>, bool),
    Group(Option<Box<Node>>, bool),
    Post(Post, Box<Node>),
}

/// Builds a tree from tokens, accepting incomplete input (`2+`, `(3+4`) so the
/// same tree drives live rendering and evaluation.
pub fn parse(tokens: &[Tok]) -> Option<Node> {
    if tokens.is_empty() {
        return None;
    }
    let mut p = Parser { tokens, i: 0 };
    let mut node = p.expression(0);
    while !p.at_end() {
        p.i += 1; // skip a stray token (e.g. an unmatched close) and keep going
        if !p.at_end() {
            let rhs = p.expression(0);
            node = Node::Bin(Op::Mul, Box::new(node), Some(Box::new(rhs)));
        }
    }
    Some(node)
}

struct Parser<'a> {
    tokens: &'a [Tok],
    i: usize,
}

impl<'a> Parser<'a> {
    fn at_end(&self) -> bool {
        self.i >= self.tokens.len()
    }
    fn peek(&self) -> Option<&'a Tok> {
        self.tokens.get(self.i)
    }

    fn parenthesised(&mut self) -> (Option<Box<Node>>, bool) {
        match self.peek() {
            None => (None, false),
            Some(Tok::Close) => {
                self.i += 1;
                (None, true)
            }
            Some(_) => {
                let inner = self.expression(0);
                if let Some(Tok::Close) = self.peek() {
                    self.i += 1;
                    (Some(Box::new(inner)), true)
                } else {
                    (Some(Box::new(inner)), false)
                }
            }
        }
    }

    fn primary(&mut self) -> Node {
        let Some(tok) = self.peek() else { return Node::Empty };
        match tok {
            Tok::Num(t, b) => {
                self.i += 1;
                Node::Num(t.clone(), *b)
            }
            Tok::Const(c) => {
                self.i += 1;
                Node::Const(c.clone())
            }
            Tok::Open => {
                self.i += 1;
                let (inner, closed) = self.parenthesised();
                Node::Group(inner, closed)
            }
            Tok::Pre(f) => {
                let f = *f;
                self.i += 1;
                if let Some(Tok::Open) = self.peek() {
                    self.i += 1;
                }
                let (inner, closed) = self.parenthesised();
                Node::Pre(f, inner, closed)
            }
            _ => Node::Empty,
        }
    }

    fn expression(&mut self, min: u8) -> Node {
        let mut lhs = self.primary();
        while let Some(tok) = self.peek() {
            match tok {
                Tok::Post(op) => {
                    self.i += 1;
                    lhs = Node::Post(*op, Box::new(lhs));
                }
                Tok::Bin(op) if op.precedence() >= min => {
                    let op = *op;
                    self.i += 1;
                    if self.at_end() || self.peek() == Some(&Tok::Close) {
                        lhs = Node::Bin(op, Box::new(lhs), None);
                        continue;
                    }
                    let next = if op == Op::Pow { op.precedence() } else { op.precedence() + 1 };
                    let rhs = self.expression(next);
                    lhs = Node::Bin(op, Box::new(lhs), Some(Box::new(rhs)));
                }
                _ => break,
            }
        }
        lhs
    }
}

// ── Numbers as typed ────────────────────────────────────────────────────

pub fn parse_int_text(text: &str, base: u32) -> BigInt {
    let (neg, digits) = match text.strip_prefix('-') {
        Some(d) => (true, d),
        None => (false, text),
    };
    let mut v = BigInt::from(0u8);
    for ch in digits.chars() {
        match ch.to_digit(36) {
            Some(d) if d < base => v = v * base + d,
            _ => break,
        }
    }
    if neg {
        -v
    } else {
        v
    }
}

pub fn parse_number(text: &str, base: u32) -> Dec {
    if base != 10 {
        return Dec::from_i64(wrap_i64(&parse_int_text(text, base)));
    }
    let t = text.strip_suffix('.').unwrap_or(text);
    if t.is_empty() || t == "-" {
        return Dec::zero();
    }
    Dec::parse(t).unwrap_or_else(Dec::zero)
}

// ── Decimal evaluator ───────────────────────────────────────────────────

fn from_f64(v: f64) -> Calc<Dec> {
    if v.is_nan() {
        return Err(CalcError::Domain);
    }
    Dec::from_f64(v).ok_or(CalcError::Undefined)
}

fn int_pow(a: &Dec, b: &Dec) -> Calc<Dec> {
    if let Some(n) = b.to_small_int() {
        if n.abs() <= 400 {
            if n < 0 && a.is_zero() {
                return Err(CalcError::Undefined);
            }
            return a.pow_int(n).ok_or(CalcError::Undefined);
        }
    }
    if a.sign() < 0 {
        return Err(CalcError::Domain);
    }
    from_f64(a.to_f64().powf(b.to_f64()))
}

/// Lanczos approximation for non-integer factorials.
fn gamma(z: f64) -> f64 {
    if z < 0.5 {
        return std::f64::consts::PI / ((std::f64::consts::PI * z).sin() * gamma(1.0 - z));
    }
    const C: [f64; 9] = [
        0.999_999_999_999_809_9, 676.520_368_121_885_1, -1_259.139_216_722_402_8, 771.323_428_777_653_1,
        -176.615_029_162_140_6, 12.507_343_278_686_905, -0.138_571_095_265_720_12,
        9.984_369_578_019_571_6e-6, 1.505_632_735_149_311_6e-7,
    ];
    let z = z - 1.0;
    let mut x = C[0];
    for (k, c) in C.iter().enumerate().skip(1) {
        x += c / (z + k as f64);
    }
    let t = z + 7.5;
    (2.0 * std::f64::consts::PI).sqrt() * t.powf(z + 0.5) * (-t).exp() * x
}

fn factorial(x: &Dec) -> Calc<Dec> {
    if let Some(n) = x.to_small_int() {
        if !(0..=170).contains(&n) {
            return Err(CalcError::Domain);
        }
        let mut r = BigInt::from(1u8);
        for k in 2..=n {
            r *= k;
        }
        return Ok(Dec::from_bigint(r));
    }
    if x.sign() < 0 {
        return Err(CalcError::Domain);
    }
    from_f64(gamma(x.to_f64() + 1.0))
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Angle {
    Deg,
    Rad,
}

pub struct Evaluator {
    pub angle: Angle,
}

impl Evaluator {
    pub fn evaluate(&self, node: &Node) -> Calc<Dec> {
        match node {
            Node::Empty => Ok(Dec::zero()),
            Node::Num(t, b) => Ok(parse_number(t, *b)),
            Node::Const(Constant::Pi) => Ok(dec::pi()),
            Node::Const(Constant::E) => Ok(dec::e()),
            Node::Const(Constant::Value(v)) => Ok(v.clone()),
            Node::Group(inner, _) => match inner {
                Some(n) => self.evaluate(n),
                None => Ok(Dec::zero()),
            },
            Node::Pre(f, inner, _) => {
                let x = match inner {
                    Some(n) => self.evaluate(n)?,
                    None => Dec::zero(),
                };
                self.apply(*f, &x)
            }
            Node::Post(op, x) => {
                let x = self.evaluate(x)?;
                match op {
                    Post::Sq => Ok(x.mul(&x)),
                    Post::Cube => Ok(x.mul(&x).mul(&x)),
                    Post::Fact => factorial(&x),
                    Post::Pct => x.div(&Dec::from_i64(100)).ok_or(CalcError::Undefined),
                }
            }
            Node::Bin(op, l, r) => {
                let a = self.evaluate(l)?;
                let Some(r) = r else { return self.binary(*op, &a, &a) }; // `2+=` reuses the left operand
                // `a ± b%` is "a plus b percent of a": 200+10% = 220, 2+3% = 2.06.
                if matches!(op, Op::Add | Op::Sub) {
                    if let Node::Post(Post::Pct, pct) = r.as_ref() {
                        let share = a.mul(&self.evaluate(pct)?).div(&Dec::from_i64(100)).ok_or(CalcError::Undefined)?;
                        return Ok(if *op == Op::Add { a.add(&share) } else { a.sub(&share) });
                    }
                }
                let b = self.evaluate(r)?;
                self.binary(*op, &a, &b)
            }
        }
    }

    pub fn binary(&self, op: Op, a: &Dec, b: &Dec) -> Calc<Dec> {
        match op {
            Op::Add => Ok(a.add(b)),
            Op::Sub => Ok(a.sub(b)),
            Op::Mul => Ok(a.mul(b)),
            Op::Div => a.div(b).ok_or(CalcError::Undefined),
            Op::Mod => {
                let q = a.div(b).ok_or(CalcError::Undefined)?.trunc();
                Ok(a.sub(&q.mul(b)))
            }
            Op::Pow => int_pow(a, b),
            Op::Rpow => int_pow(b, a),
            Op::Root => {
                if b.is_zero() {
                    return Err(CalcError::Undefined);
                }
                let odd = b.to_small_int().map(|n| n % 2 != 0).unwrap_or(false);
                if a.sign() < 0 && odd {
                    return from_f64(-(-a.to_f64()).powf(1.0 / b.to_f64()));
                }
                if a.sign() < 0 {
                    return Err(CalcError::Domain);
                }
                from_f64(a.to_f64().powf(1.0 / b.to_f64()))
            }
            Op::Logy => {
                if a.sign() <= 0 || b.sign() <= 0 || b.eq_i64(1) {
                    return Err(CalcError::Domain);
                }
                from_f64(a.to_f64().ln() / b.to_f64().ln())
            }
            Op::Ee => Ok(a.mul(&int_pow(&Dec::from_i64(10), b)?)),
            _ => Ok(Dec::from_i64(int_binary(op, a.to_i64_wrapping(), b.to_i64_wrapping())?)),
        }
    }

    pub fn apply(&self, f: Func, x: &Dec) -> Calc<Dec> {
        let deg = self.angle == Angle::Deg;
        let to_rad = if deg { std::f64::consts::PI / 180.0 } else { 1.0 };
        let from_rad = if deg { 180.0 / std::f64::consts::PI } else { 1.0 };
        let d = x.to_f64();
        match f {
            Func::Sin | Func::Cos | Func::Tan => {
                let mut a = x.clone();
                if deg {
                    // Reduce exactly so sin(180) is 0 rather than 1.2e-16.
                    let turns = a.div(&Dec::from_i64(360)).ok_or(CalcError::Undefined)?.floor();
                    a = a.sub(&turns.mul(&Dec::from_i64(360)));
                    if f == Func::Tan && (a.eq_i64(90) || a.eq_i64(270)) {
                        return Err(CalcError::Domain);
                    }
                }
                let r = a.to_f64() * to_rad;
                let v = match f {
                    Func::Sin => r.sin(),
                    Func::Cos => r.cos(),
                    _ => r.tan(),
                };
                from_f64(if v.abs() < 1e-15 { 0.0 } else { v })
            }
            Func::Asin | Func::Acos => {
                if !(-1.0..=1.0).contains(&d) {
                    return Err(CalcError::Domain);
                }
                from_f64(if f == Func::Asin { d.asin() } else { d.acos() } * from_rad)
            }
            Func::Atan => from_f64(d.atan() * from_rad),
            Func::Sinh => from_f64(d.sinh()),
            Func::Cosh => from_f64(d.cosh()),
            Func::Tanh => from_f64(d.tanh()),
            Func::Asinh => from_f64(d.asinh()),
            Func::Acosh => {
                if d < 1.0 {
                    return Err(CalcError::Domain);
                }
                from_f64(d.acosh())
            }
            Func::Atanh => {
                if d <= -1.0 || d >= 1.0 {
                    return Err(CalcError::Domain);
                }
                from_f64(d.atanh())
            }
            Func::Sqrt => {
                if x.sign() < 0 {
                    return Err(CalcError::Domain);
                }
                from_f64(d.sqrt())
            }
            Func::Cbrt => from_f64(d.cbrt()),
            Func::Ln => {
                if x.sign() <= 0 {
                    return Err(CalcError::Domain);
                }
                from_f64(d.ln())
            }
            Func::Log10 => {
                if x.sign() <= 0 {
                    return Err(CalcError::Domain);
                }
                if let Some(e) = x.is_power_of_ten() {
                    return Ok(Dec::from_i64(e as i64)); // exact powers of ten
                }
                from_f64(d.log10())
            }
            Func::Log2 => {
                if x.sign() <= 0 {
                    return Err(CalcError::Domain);
                }
                from_f64(d.log2())
            }
            Func::Exp => from_f64(d.exp()),
            Func::TenPow => int_pow(&Dec::from_i64(10), x),
            Func::TwoPow => int_pow(&Dec::from_i64(2), x),
            Func::Recip => Dec::from_i64(1).div(x).ok_or(CalcError::Undefined),
            Func::Neg => Ok(x.neg()),
            _ => Ok(Dec::from_i64(int_unary(f, x.to_i64_wrapping()))),
        }
    }
}

// ── 64-bit integer evaluator (Programmer) ───────────────────────────────

pub fn int_binary(op: Op, a: i64, b: i64) -> Calc<i64> {
    Ok(match op {
        Op::Add => a.wrapping_add(b),
        Op::Sub => a.wrapping_sub(b),
        Op::Mul => a.wrapping_mul(b),
        Op::Div => {
            if b == 0 {
                return Err(CalcError::Undefined);
            }
            a.wrapping_div(b)
        }
        Op::Mod => {
            if b == 0 {
                return Err(CalcError::Undefined);
            }
            a.wrapping_rem(b)
        }
        Op::And => a & b,
        Op::Or => a | b,
        Op::Xor => a ^ b,
        Op::Nor => !(a | b),
        Op::Shl => if (0..64).contains(&b) { ((a as u64) << b) as i64 } else { 0 },
        Op::Shr => if (0..64).contains(&b) { ((a as u64) >> b) as i64 } else { 0 },
        Op::Pow | Op::Rpow => {
            let (x, y) = if op == Op::Pow { (a, b) } else { (b, a) };
            if y < 0 {
                return Ok(0);
            }
            let mut r: i64 = 1;
            for _ in 0..y.min(64) {
                r = r.wrapping_mul(x);
            }
            r
        }
        _ => a,
    })
}

pub fn int_unary(f: Func, x: i64) -> i64 {
    let u = x as u64;
    match f {
        Func::Not => !x,
        Func::Neg | Func::TwosNeg => x.wrapping_neg(),
        Func::Rol => u.rotate_left(1) as i64,
        Func::Ror => u.rotate_right(1) as i64,
        // flip₈: swap the bytes of the low 16 bits (0xABCD → 0xCDAB).
        Func::Flip8 => {
            let low = u & 0xFFFF;
            ((u & !0xFFFF) | ((low & 0xFF) << 8) | (low >> 8)) as i64
        }
        // flip₁₆: swap the 16-bit words of the low 32 bits (0xABCD1234 → 0x1234ABCD).
        Func::Flip16 => {
            let low = u & 0xFFFF_FFFF;
            ((u & !0xFFFF_FFFF) | ((low & 0xFFFF) << 16) | (low >> 16)) as i64
        }
        _ => x,
    }
}

pub fn evaluate_int(node: &Node) -> Calc<i64> {
    Ok(match node {
        Node::Empty => 0,
        Node::Num(t, b) => {
            if *b == 10 {
                parse_number(t, 10).to_i64_wrapping()
            } else {
                wrap_i64(&parse_int_text(t, *b))
            }
        }
        Node::Const(Constant::Value(v)) => v.to_i64_wrapping(),
        Node::Const(_) => 0,
        Node::Group(inner, _) => match inner {
            Some(n) => evaluate_int(n)?,
            None => 0,
        },
        Node::Pre(f, inner, _) => int_unary(*f, match inner {
            Some(n) => evaluate_int(n)?,
            None => 0,
        }),
        Node::Post(op, x) => {
            let x = evaluate_int(x)?;
            match op {
                Post::Sq => x.wrapping_mul(x),
                Post::Cube => x.wrapping_mul(x).wrapping_mul(x),
                Post::Fact => {
                    if x < 0 {
                        return Err(CalcError::Domain);
                    }
                    let mut r: i64 = 1;
                    for k in 2..=x.min(25) {
                        r = r.wrapping_mul(k);
                    }
                    r
                }
                Post::Pct => x / 100,
            }
        }
        Node::Bin(op, l, r) => {
            let a = evaluate_int(l)?;
            let b = match r {
                Some(r) => evaluate_int(r)?,
                None => a,
            };
            int_binary(*op, a, b)?
        }
    })
}

/// Unsigned digits in base 8/16, signed in base 10 (as Calculator shows them).
pub fn integer_string(v: i64, base: u32) -> String {
    match base {
        10 => v.to_string(),
        8 => format!("{:o}", v as u64),
        16 => format!("{:X}", v as u64),
        2 => format!("{:b}", v as u64),
        _ => v.to_string(),
    }
}
