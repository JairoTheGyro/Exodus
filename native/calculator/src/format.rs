//! Display formatting and expression rendering.
//!
//! Rules recovered from Calculator 12.0: at most 8 fraction digits, rounded;
//! integers below 1e20 in full with grouping; ≥ 1e20 or < 1e-8 in e-notation
//! with up to 8 significant digits (`9.9999997e23`, `1e-12`).

use crate::dec::Dec;
use crate::engine::{parse, Constant, Func, Node, Op, Post, Tok};

pub const MAX_FRACTION_DIGITS: u32 = 8;
const SCI_DIGITS: u32 = 8;

#[derive(Clone, Debug)]
pub struct NumberFormat {
    pub grouping: bool,
    /// None = automatic (≤ 8 fraction digits); Some(n) = View ▸ Decimal Places.
    pub places: Option<u32>,
    pub group_sep: String,
    pub decimal_sep: String,
}

impl Default for NumberFormat {
    fn default() -> Self {
        NumberFormat { grouping: true, places: None, group_sep: ",".into(), decimal_sep: ".".into() }
    }
}

impl NumberFormat {
    pub fn format(&self, v: &Dec) -> String {
        if v.is_zero() {
            return match self.places {
                Some(p) if p > 0 => format!("0{}{}", self.decimal_sep, "0".repeat(p as usize)),
                _ => "0".into(),
            };
        }
        let rounded = v.round(self.places.unwrap_or(MAX_FRACTION_DIGITS));
        let e20 = Dec::parse("1e20").unwrap();
        if !v.abs().lt(&e20) || rounded.is_zero() {
            return self.scientific(v);
        }
        self.plain(&rounded)
    }

    fn plain(&self, v: &Dec) -> String {
        let text = v.to_plain();
        let (neg, body) = match text.strip_prefix('-') {
            Some(b) => (true, b),
            None => (false, text.as_str()),
        };
        let (int, frac) = match body.find('.') {
            Some(i) => (&body[..i], &body[i + 1..]),
            None => (body, ""),
        };
        let frac = match self.places {
            Some(p) => format!("{:0<width$}", frac, width = p as usize),
            None => frac.trim_end_matches('0').to_string(),
        };
        let mut out = String::new();
        if neg {
            out.push('-');
        }
        out.push_str(&self.group(if int.is_empty() { "0" } else { int }));
        if !frac.is_empty() {
            out.push_str(&self.decimal_sep);
            out.push_str(&frac);
        }
        out
    }

    fn scientific(&self, v: &Dec) -> String {
        let neg = v.sign() < 0;
        let (digits, mut exponent) = v.sci_parts();
        let mantissa_text = format!("{}.{}", &digits[..1], &digits[1..]);
        let mut mantissa = Dec::parse(&mantissa_text).unwrap_or_else(Dec::zero).round(SCI_DIGITS - 1);
        if !mantissa.lt(&Dec::from_i64(10)) {
            mantissa = mantissa.div(&Dec::from_i64(10)).unwrap_or_else(Dec::zero);
            exponent += 1;
        }
        let mut text = mantissa.to_plain();
        if text.contains('.') {
            text = text.trim_end_matches('0').trim_end_matches('.').to_string();
        }
        format!("{}{}e{}", if neg { "-" } else { "" }, text.replace('.', &self.decimal_sep), exponent)
    }

    pub fn group(&self, int: &str) -> String {
        if !self.grouping || int.len() <= 3 {
            return int.to_string();
        }
        let n = int.len();
        let mut out = String::with_capacity(n + n / 3 * self.group_sep.len());
        for (i, ch) in int.chars().enumerate() {
            if i > 0 && (n - i) % 3 == 0 {
                out.push_str(&self.group_sep);
            }
            out.push(ch);
        }
        out
    }

    /// A number exactly as typed (keeps `1.50` and a trailing point), plus grouping.
    pub fn typed(&self, text: &str) -> String {
        let (neg, body) = match text.strip_prefix('-') {
            Some(b) => (true, b),
            None => (false, text),
        };
        let mut out = String::new();
        if neg {
            out.push('-');
        }
        match body.find('.') {
            Some(i) => {
                out.push_str(&self.group(if i == 0 { "0" } else { &body[..i] }));
                out.push_str(&self.decimal_sep);
                out.push_str(&body[i + 1..]);
            }
            None => out.push_str(&self.group(if body.is_empty() { "0" } else { body })),
        }
        out
    }
}

/// A run of display text. `level` > 0 is superscript depth, < 0 subscript.
#[derive(Clone, Debug, PartialEq)]
pub struct Span {
    pub text: String,
    pub level: i32,
    pub italic: bool,
}

pub fn plain_text(spans: &[Span]) -> String {
    spans.iter().map(|s| s.text.as_str()).collect()
}

/// Renders an expression the way Calculator draws it: `sin(30)`, `√(2)`,
/// `2¹⁰`, `5!`, `41₁₆+1₁₆`.
pub fn render(tokens: &[Tok], fmt: &NumberFormat, shows_base: bool) -> Vec<Span> {
    let Some(node) = parse(tokens) else { return Vec::new() };
    let mut r = Renderer { fmt, shows_base, out: Vec::new() };
    r.emit(&node, 0);
    // Merge neighbouring spans that share a style.
    let mut merged: Vec<Span> = Vec::new();
    for s in r.out.into_iter().filter(|s| !s.text.is_empty()) {
        match merged.last_mut() {
            Some(last) if last.level == s.level && last.italic == s.italic => last.text.push_str(&s.text),
            _ => merged.push(s),
        }
    }
    merged
}

struct Renderer<'a> {
    fmt: &'a NumberFormat,
    shows_base: bool,
    out: Vec<Span>,
}

impl<'a> Renderer<'a> {
    fn text(&mut self, s: &str, level: i32) {
        self.out.push(Span { text: s.to_string(), level, italic: false });
    }
    fn italic(&mut self, s: &str, level: i32) {
        self.out.push(Span { text: s.to_string(), level, italic: true });
    }

    fn wrapped(&mut self, inner: Option<&Node>, closed: bool, level: i32) {
        self.text("(", level);
        if let Some(n) = inner {
            self.emit(n, level);
        }
        if closed {
            self.text(")", level);
        }
    }

    /// Group nodes already carry their own parentheses.
    fn operand(&mut self, inner: Option<&Node>, closed: bool, level: i32) {
        match inner {
            Some(Node::Group(g, c)) => self.wrapped(g.as_deref(), *c, level),
            other => self.wrapped(other, closed, level),
        }
    }

    /// `e`, `10` and `2` powers draw their argument as a superscript, without
    /// parentheses when it is a single value.
    fn exponent(&mut self, inner: Option<&Node>, closed: bool, level: i32) {
        match inner {
            None => self.text("x", level + 1),
            Some(n @ (Node::Num(..) | Node::Const(_) | Node::Post(..))) => self.emit(n, level + 1),
            Some(n) => {
                self.text("(", level + 1);
                self.emit(n, level + 1);
                if closed {
                    self.text(")", level + 1);
                }
            }
        }
    }

    fn emit(&mut self, node: &Node, level: i32) {
        match node {
            Node::Empty => {}
            Node::Num(t, base) => {
                let shown = if *base == 10 { self.fmt.typed(t) } else { t.to_uppercase() };
                self.text(&shown, level);
                if self.shows_base {
                    self.text(&base.to_string(), level - 1);
                }
            }
            Node::Const(Constant::Pi) => self.text("π", level),
            Node::Const(Constant::E) => self.italic("e", level),
            Node::Const(Constant::Value(v)) => {
                let s = self.fmt.format(v);
                self.text(&s, level);
            }
            Node::Group(inner, closed) => self.wrapped(inner.as_deref(), *closed, level),
            Node::Post(op, x) => {
                self.emit(x, level);
                match op {
                    Post::Sq => self.text("2", level + 1),
                    Post::Cube => self.text("3", level + 1),
                    Post::Fact => self.text("!", level),
                    Post::Pct => self.text("%", level),
                }
            }
            Node::Bin(op, l, r) => match op {
                Op::Pow => {
                    self.emit(l, level);
                    match r {
                        Some(r) => self.emit(r, level + 1),
                        None => self.text("y", level + 1),
                    }
                }
                Op::Rpow => {
                    match r {
                        Some(r) => self.emit(r, level),
                        None => self.text("y", level),
                    }
                    self.emit(l, level + 1);
                }
                Op::Root | Op::Logy => {
                    if *op == Op::Root {
                        match r {
                            Some(r) => self.emit(r, level + 1),
                            None => self.text("y", level + 1),
                        }
                        self.text("√", level);
                    } else {
                        self.text("log", level);
                        match r {
                            Some(r) => self.emit(r, level - 1),
                            None => self.text("y", level - 1),
                        }
                    }
                    if matches!(l.as_ref(), Node::Group(..)) {
                        self.emit(l, level);
                    } else {
                        self.text("(", level);
                        self.emit(l, level);
                        self.text(")", level);
                    }
                }
                _ => {
                    self.emit(l, level);
                    self.text(op.symbol(), level);
                    if let Some(r) = r {
                        self.emit(r, level);
                    }
                }
            },
            Node::Pre(f, inner, closed) => {
                let inner = inner.as_deref();
                match f {
                    Func::Exp => {
                        self.italic("e", level);
                        self.exponent(inner, *closed, level);
                    }
                    Func::TenPow | Func::TwoPow => {
                        self.text(f.name(), level);
                        self.exponent(inner, *closed, level);
                    }
                    Func::Cbrt => {
                        self.text("3", level + 1);
                        self.text("√", level);
                        self.operand(inner, *closed, level);
                    }
                    Func::Log10 | Func::Log2 => {
                        self.text("log", level);
                        self.text(if *f == Func::Log10 { "10" } else { "2" }, level - 1);
                        self.operand(inner, *closed, level);
                    }
                    Func::Asin | Func::Acos | Func::Atan | Func::Asinh | Func::Acosh | Func::Atanh => {
                        self.text(f.name(), level);
                        self.text("-1", level + 1);
                        self.operand(inner, *closed, level);
                    }
                    Func::Flip8 | Func::Flip16 => {
                        self.text("flip", level);
                        self.text(if *f == Func::Flip8 { "8" } else { "16" }, level - 1);
                        self.operand(inner, *closed, level);
                    }
                    _ => {
                        self.text(f.name(), level);
                        self.operand(inner, *closed, level);
                    }
                }
            }
        }
    }
}
