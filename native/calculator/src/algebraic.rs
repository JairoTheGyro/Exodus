//! Expression entry for Basic, Scientific and Programmer modes.
//!
//! Observed in Calculator 12.0: `12+3×4=` → 24 (precedence); `2+3===` → 11
//! with the line `8+3` (repeat the last operation); a digit after `=` starts
//! over while an operator continues from the result; a second operator
//! replaces the first (`2+×3` → `2×3`); `5+=` does nothing; ± with no operand
//! does nothing.

use crate::dec::{wrap_i64, Dec};
use crate::engine::{
    evaluate_int, integer_string, parse, parse_int_text, parse_number, Angle, Calc, CalcError, Constant,
    Evaluator, Func, Op, Post, Tok,
};
use num_bigint::BigInt;

const MAX_DIGITS: usize = 20;

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Kind {
    Decimal,
    Programmer,
}

fn depth(tokens: &[Tok]) -> usize {
    let mut d = 0usize;
    for t in tokens {
        match t {
            Tok::Open => d += 1,
            Tok::Close if d > 0 => d -= 1,
            _ => {}
        }
    }
    d
}

pub struct Algebraic {
    pub kind: Kind,
    pub angle: Angle,
    pub base: u32,
    pub tokens: Vec<Tok>,
    /// The expression shown above a result after `=`.
    pub evaluated: Option<Vec<Tok>>,
    pub result: Option<Dec>,
    pub int_result: Option<i64>,
    pub error: Option<CalcError>,
    repeat_op: Option<Op>,
    repeat_operand: Vec<Tok>,
}

impl Algebraic {
    pub fn new(kind: Kind) -> Self {
        Algebraic {
            kind,
            angle: Angle::Deg,
            base: 10,
            tokens: Vec::new(),
            evaluated: None,
            result: None,
            int_result: None,
            error: None,
            repeat_op: None,
            repeat_operand: Vec::new(),
        }
    }

    pub fn showing_result(&self) -> bool {
        self.evaluated.is_some()
    }
    pub fn shows_all_clear(&self) -> bool {
        self.tokens.is_empty() || self.showing_result()
    }
    fn number_base(&self) -> u32 {
        if self.kind == Kind::Programmer { self.base } else { 10 }
    }
    fn last(&self) -> Option<&Tok> {
        self.tokens.last()
    }

    pub fn input_digit(&mut self, d: &str) {
        let digit = d.to_uppercase();
        if self.kind == Kind::Programmer {
            match u32::from_str_radix(&digit, 16) {
                Ok(v) if v < self.base => {}
                _ => return,
            }
        }
        self.begin(false);
        if let Some(Tok::Num(text, b)) = self.tokens.last().cloned() {
            if text.chars().filter(|c| c.is_ascii_alphanumeric()).count() >= MAX_DIGITS {
                return;
            }
            let next = if text == "0" {
                digit
            } else if text == "-0" {
                format!("-{}", digit)
            } else {
                format!("{}{}", text, digit)
            };
            if self.kind == Kind::Programmer && overflows(&next, b) {
                return;
            }
            *self.tokens.last_mut().unwrap() = Tok::Num(next, b);
        } else {
            self.implicit_multiply();
            self.tokens.push(Tok::Num(digit, self.number_base()));
        }
    }

    pub fn input_point(&mut self) {
        if self.kind != Kind::Decimal {
            return;
        }
        self.begin(false);
        if let Some(Tok::Num(text, b)) = self.tokens.last().cloned() {
            if text.contains('.') {
                return;
            }
            let base = if text == "-" { "-0".to_string() } else { text };
            *self.tokens.last_mut().unwrap() = Tok::Num(format!("{}.", base), b);
        } else {
            self.implicit_multiply();
            self.tokens.push(Tok::Num("0.".into(), 10));
        }
    }

    pub fn input_operator(&mut self, op: Op) {
        self.begin(true);
        let nb = self.number_base();
        match self.last().cloned() {
            None => {
                self.tokens = if op == Op::Sub {
                    vec![Tok::Num("-".into(), nb)]
                } else {
                    vec![Tok::Num("0".into(), nb), Tok::Bin(op)]
                };
            }
            Some(Tok::Bin(_)) => *self.tokens.last_mut().unwrap() = Tok::Bin(op), // `2+×3` → `2×3`
            Some(Tok::Open) | Some(Tok::Pre(_)) => {
                if op == Op::Sub {
                    self.tokens.push(Tok::Num("-".into(), nb));
                }
            }
            Some(Tok::Num(t, _)) if t == "-" => {}
            Some(_) => self.tokens.push(Tok::Bin(op)),
        }
    }

    pub fn open_paren(&mut self) {
        self.begin(false);
        self.implicit_multiply();
        self.tokens.push(Tok::Open);
    }

    pub fn close_paren(&mut self) {
        let ends = self.last().map(Tok::ends_operand).unwrap_or(false);
        if self.showing_result() || depth(&self.tokens) == 0 || !ends {
            return;
        }
        self.tokens.push(Tok::Close);
    }

    /// Wraps the last operand (`30` → `sin(30)`), or opens `sin(` when there is none.
    pub fn apply_function(&mut self, f: Func) {
        self.begin(true);
        match self.last_operand_range() {
            Some((start, end)) => {
                if self.tokens[start] == Tok::Open {
                    self.tokens.insert(start, Tok::Pre(f));
                } else {
                    self.tokens.insert(end, Tok::Close);
                    self.tokens.splice(start..start, [Tok::Pre(f), Tok::Open]);
                }
            }
            None => {
                self.implicit_multiply();
                self.tokens.push(Tok::Pre(f));
                self.tokens.push(Tok::Open);
            }
        }
    }

    pub fn apply_postfix(&mut self, op: Post) {
        self.begin(true);
        let Some(last) = self.last() else { return };
        if !last.ends_operand() {
            return;
        }
        if op == Post::Pct && *last == Tok::Post(Post::Pct) {
            return;
        }
        self.tokens.push(Tok::Post(op));
    }

    /// Programmer `<<` / `>>`: shift the last operand by one bit, shown as `(x<<1)`.
    pub fn shift_by_one(&mut self, left: bool) {
        self.begin(true);
        let Some((start, end)) = self.last_operand_range() else { return };
        let op = if left { Op::Shl } else { Op::Shr };
        self.tokens.splice(end..end, [Tok::Bin(op), Tok::Num("1".into(), 10), Tok::Close]);
        self.tokens.insert(start, Tok::Open);
    }

    pub fn input_constant(&mut self, c: Constant) {
        self.begin(false);
        self.implicit_multiply();
        self.tokens.push(Tok::Const(c));
    }

    /// Inserts a value (memory recall, history, paste).
    pub fn input_value(&mut self, v: &Dec) {
        if self.kind == Kind::Programmer {
            self.begin(false);
            self.implicit_multiply();
            let text = integer_string(v.to_i64_wrapping(), self.base);
            self.tokens.push(Tok::Num(text, self.base));
        } else {
            self.input_constant(Constant::Value(v.clone()));
        }
    }

    pub fn toggle_sign(&mut self) {
        self.begin(true);
        match self.last().cloned() {
            Some(Tok::Num(text, b)) => {
                let t = match text.strip_prefix('-') {
                    Some(rest) => rest.to_string(),
                    None => format!("-{}", text),
                };
                if t.is_empty() {
                    self.tokens.pop();
                } else {
                    *self.tokens.last_mut().unwrap() = Tok::Num(t, b);
                }
            }
            Some(Tok::Const(Constant::Value(v))) => {
                *self.tokens.last_mut().unwrap() = Tok::Const(Constant::Value(v.neg()));
            }
            _ => {
                if self.last_operand_range().is_some() {
                    self.apply_function(Func::Neg);
                }
                // Observed: ± with no operand does nothing.
            }
        }
    }

    pub fn backspace(&mut self) {
        if self.showing_result() {
            self.clear_all();
            return;
        }
        self.error = None;
        match self.tokens.pop() {
            Some(Tok::Num(mut text, b)) => {
                text.pop();
                if !(text.is_empty() || text == "-") {
                    self.tokens.push(Tok::Num(text, b));
                }
            }
            Some(Tok::Open) => {
                if let Some(Tok::Pre(_)) = self.last() {
                    self.tokens.pop();
                }
            }
            _ => {}
        }
    }

    /// `C` clears the input; `AC` (shown when already clear) also forgets the repeat operation.
    pub fn clear(&mut self) {
        if self.shows_all_clear() {
            self.clear_all();
        } else {
            self.tokens.clear();
            self.error = None;
        }
    }

    pub fn clear_all(&mut self) {
        self.tokens.clear();
        self.evaluated = None;
        self.result = None;
        self.int_result = None;
        self.error = None;
        self.repeat_op = None;
        self.repeat_operand.clear();
    }

    /// Evaluates; returns the evaluated tokens and value for history.
    pub fn equals(&mut self) -> Option<(Vec<Tok>, Dec)> {
        let mut expr = self.tokens.clone();
        if self.showing_result() {
            let ans = self.current_value()?;
            let op = self.repeat_op?;
            expr = vec![self.answer_token(&ans), Tok::Bin(op)];
            expr.extend(self.repeat_operand.iter().cloned());
        } else {
            match expr.last() {
                None => return None,
                Some(Tok::Bin(_)) => return None, // observed: `5+=` does nothing
                Some(Tok::Open) => {
                    expr.pop();
                    if let Some(Tok::Pre(_)) = expr.last() {
                        expr.pop();
                    }
                }
                _ => {}
            }
            if expr.is_empty() {
                return None;
            }
            for _ in 0..depth(&expr) {
                expr.push(Tok::Close);
            }
            self.capture_repeat(&expr);
        }
        match self.evaluate(&expr, true) {
            Ok(value) => {
                self.evaluated = Some(expr.clone());
                self.tokens.clear();
                self.error = None;
                Some((expr, value))
            }
            Err(e) => {
                self.evaluated = Some(expr);
                self.tokens.clear();
                self.result = None;
                self.int_result = None;
                self.error = Some(e);
                None
            }
        }
    }

    /// Value of the expression typed so far (live converter, bit grid).
    pub fn current_value(&self) -> Option<Dec> {
        if self.showing_result() {
            return match self.kind {
                Kind::Programmer => self.int_result.map(Dec::from_i64),
                Kind::Decimal => self.result.clone(),
            };
        }
        if self.tokens.is_empty() {
            return self.result.clone();
        }
        let mut expr = self.tokens.clone();
        while let Some(Tok::Bin(_)) = expr.last() {
            expr.pop();
        }
        for _ in 0..depth(&expr) {
            expr.push(Tok::Close);
        }
        self.preview(&expr).ok()
    }

    /// The integer being typed (Programmer bit grid).
    pub fn current_operand_int(&self) -> i64 {
        if let Some(Tok::Num(t, b)) = self.last() {
            return parse_number(t, *b).to_i64_wrapping();
        }
        if self.showing_result() || self.tokens.is_empty() {
            return self.int_result.unwrap_or(0);
        }
        self.current_value().map(|v| v.to_i64_wrapping()).unwrap_or(0)
    }

    pub fn set_current_operand(&mut self, v: i64) {
        let text = integer_string(v, self.base);
        if matches!(self.last(), Some(Tok::Num(..))) && !self.showing_result() {
            *self.tokens.last_mut().unwrap() = Tok::Num(text, self.base);
        } else {
            self.begin(false);
            self.implicit_multiply();
            self.tokens.push(Tok::Num(text, self.base));
        }
    }

    pub fn convert_base(&mut self, new_base: u32) {
        self.base = new_base;
        for t in self.tokens.iter_mut() {
            if let Tok::Num(text, b) = t {
                if *b != new_base {
                    let v = wrap_i64(&parse_int_text(text, *b));
                    *t = Tok::Num(integer_string(v, new_base), new_base);
                }
            }
        }
    }

    // internals

    fn answer_token(&self, v: &Dec) -> Tok {
        match self.kind {
            Kind::Programmer => Tok::Num(integer_string(v.to_i64_wrapping(), self.base), self.base),
            Kind::Decimal => Tok::Const(Constant::Value(v.clone())),
        }
    }

    /// After a result, operators continue from it and everything else starts fresh.
    fn begin(&mut self, continuing: bool) {
        if !self.showing_result() {
            self.error = None;
            return;
        }
        let ans = if self.error.is_some() { None } else { self.current_value() };
        self.evaluated = None;
        self.error = None;
        self.tokens = match (continuing, ans) {
            (true, Some(a)) => vec![self.answer_token(&a)],
            _ => Vec::new(),
        };
    }

    fn implicit_multiply(&mut self) {
        if self.last().map(Tok::ends_operand).unwrap_or(false) {
            self.tokens.push(Tok::Bin(Op::Mul));
        }
    }

    fn evaluate(&mut self, expr: &[Tok], store: bool) -> Calc<Dec> {
        let Some(node) = parse(expr) else { return Ok(Dec::zero()) };
        if self.kind == Kind::Programmer {
            let v = evaluate_int(&node)?;
            if store {
                self.int_result = Some(v);
                self.result = Some(Dec::from_i64(v));
            }
            return Ok(Dec::from_i64(v));
        }
        let v = Evaluator { angle: self.angle }.evaluate(&node)?;
        if store {
            self.result = Some(v.clone());
        }
        Ok(v)
    }

    fn preview(&self, expr: &[Tok]) -> Calc<Dec> {
        let Some(node) = parse(expr) else { return Ok(Dec::zero()) };
        if self.kind == Kind::Programmer {
            return Ok(Dec::from_i64(evaluate_int(&node)?));
        }
        Evaluator { angle: self.angle }.evaluate(&node)
    }

    fn capture_repeat(&mut self, expr: &[Tok]) {
        let mut d = 0i32;
        let mut last: Option<usize> = None;
        for (i, t) in expr.iter().enumerate() {
            match t {
                Tok::Open => d += 1,
                Tok::Close => d -= 1,
                Tok::Bin(_) if d == 0 => last = Some(i),
                _ => {}
            }
        }
        match last {
            Some(i) if i + 1 < expr.len() => {
                if let Tok::Bin(op) = expr[i] {
                    self.repeat_op = Some(op);
                    self.repeat_operand = expr[i + 1..].to_vec();
                }
            }
            _ => {
                self.repeat_op = None;
                self.repeat_operand.clear();
            }
        }
    }

    /// [start, end) of the last complete operand, including a prefix function and trailing postfixes.
    fn last_operand_range(&self) -> Option<(usize, usize)> {
        let toks = &self.tokens;
        if !toks.last().map(Tok::ends_operand).unwrap_or(false) {
            return None;
        }
        let mut i = toks.len() as isize - 1;
        while i >= 0 && matches!(toks[i as usize], Tok::Post(_)) {
            i -= 1;
        }
        if i < 0 {
            return None;
        }
        match toks[i as usize] {
            Tok::Close => {
                let mut d = 0;
                while i >= 0 {
                    match toks[i as usize] {
                        Tok::Close => d += 1,
                        Tok::Open => {
                            d -= 1;
                            if d == 0 {
                                break;
                            }
                        }
                        _ => {}
                    }
                    i -= 1;
                }
                if i > 0 && matches!(toks[i as usize - 1], Tok::Pre(_)) {
                    i -= 1;
                }
            }
            Tok::Num(..) | Tok::Const(_) => {}
            _ => return None,
        }
        Some((i.max(0) as usize, toks.len()))
    }
}

fn overflows(text: &str, base: u32) -> bool {
    let digits = text.strip_prefix('-').unwrap_or(text);
    let v = parse_int_text(digits, base);
    let limit: BigInt = if base == 10 { BigInt::from(i64::MAX) } else { BigInt::from(u64::MAX) };
    v > limit
}
