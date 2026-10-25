//! Reverse Polish stack (View ▸ RPN Mode). Observed: `3 enter 4 enter 5`
//! shows the rows 3 / 4 / 5 with 5 still being typed.

use crate::dec::Dec;
use crate::engine::{parse_number, Angle, Calc, CalcError, Evaluator, Func, Node, Op, Post};

const MAX_DIGITS: usize = 20;

pub enum Row {
    Value(Dec),
    Typing(String),
    Error(CalcError),
}

pub struct Rpn {
    pub stack: Vec<Dec>,
    pub input: String,
    pub error: Option<CalcError>,
    pub angle: Angle,
}

impl Rpn {
    pub fn new() -> Self {
        Rpn { stack: Vec::new(), input: String::new(), error: None, angle: Angle::Deg }
    }

    pub fn rows(&self) -> Vec<Row> {
        let mut r: Vec<Row> = self.stack.iter().cloned().map(Row::Value).collect();
        if !self.input.is_empty() {
            r.push(Row::Typing(self.input.clone()));
        }
        if let Some(e) = self.error {
            r.push(Row::Error(e));
        }
        r
    }

    pub fn shows_all_clear(&self) -> bool {
        self.input.is_empty()
    }

    pub fn x(&self) -> Option<Dec> {
        if self.input.is_empty() {
            self.stack.last().cloned()
        } else {
            Some(parse_number(&self.input, 10))
        }
    }

    pub fn input_digit(&mut self, d: &str) {
        self.error = None;
        if self.input.chars().filter(char::is_ascii_digit).count() >= MAX_DIGITS {
            return;
        }
        self.input = match self.input.as_str() {
            "0" => d.to_string(),
            "-0" => format!("-{}", d),
            s => format!("{}{}", s, d),
        };
    }

    pub fn input_point(&mut self) {
        self.error = None;
        if self.input.is_empty() {
            self.input = "0.".into();
        } else if !self.input.contains('.') {
            self.input.push('.');
        }
    }

    pub fn toggle_sign(&mut self) {
        if !self.input.is_empty() {
            self.input = match self.input.strip_prefix('-') {
                Some(r) => r.to_string(),
                None => format!("-{}", self.input),
            };
        } else if let Some(top) = self.stack.pop() {
            self.stack.push(top.neg());
        }
    }

    pub fn backspace(&mut self) {
        if !self.input.is_empty() {
            self.input.pop();
            if self.input == "-" {
                self.input.clear();
            }
        } else {
            self.error = None;
        }
    }

    /// Pushes the typed value; with nothing typed, duplicates x.
    pub fn enter(&mut self) {
        self.error = None;
        if !self.input.is_empty() {
            self.stack.push(parse_number(&self.input, 10));
            self.input.clear();
        } else if let Some(top) = self.stack.last().cloned() {
            self.stack.push(top);
        }
    }

    pub fn clear(&mut self) {
        if self.input.is_empty() {
            self.stack.clear();
        }
        self.input.clear();
        self.error = None;
    }

    pub fn push(&mut self, v: Dec) {
        self.commit();
        self.stack.push(v);
    }

    /// y op x: the scientific keys become yˣ and ˣ√y.
    pub fn binary(&mut self, op: Op) {
        self.commit();
        if self.stack.len() < 2 {
            return;
        }
        let x = self.stack.pop().unwrap();
        let y = self.stack.pop().unwrap();
        let r = Evaluator { angle: self.angle }.binary(op, &y, &x);
        self.finish(r, vec![y, x]);
    }

    pub fn unary(&mut self, f: Func) {
        self.commit();
        let Some(x) = self.stack.pop() else { return };
        let r = Evaluator { angle: self.angle }.apply(f, &x);
        self.finish(r, vec![x]);
    }

    pub fn postfix(&mut self, op: Post) {
        self.commit();
        let Some(x) = self.stack.pop() else { return };
        if op == Post::Pct {
            if let Some(y) = self.stack.last().cloned() {
                let v = y.mul(&x).div(&Dec::from_i64(100)).unwrap_or_else(Dec::zero);
                self.stack.push(v);
                return;
            }
        }
        let node = Node::Post(op, Box::new(Node::Const(crate::engine::Constant::Value(x.clone()))));
        let r = Evaluator { angle: self.angle }.evaluate(&node);
        self.finish(r, vec![x]);
    }

    pub fn swap(&mut self) {
        self.commit();
        let n = self.stack.len();
        if n >= 2 {
            self.stack.swap(n - 1, n - 2);
        }
    }

    /// R↓: x moves to the top of the stack.
    pub fn roll_down(&mut self) {
        self.commit();
        if self.stack.len() >= 2 {
            let x = self.stack.pop().unwrap();
            self.stack.insert(0, x);
        }
    }

    /// R↑: the top of the stack moves to x.
    pub fn roll_up(&mut self) {
        self.commit();
        if self.stack.len() >= 2 {
            let top = self.stack.remove(0);
            self.stack.push(top);
        }
    }

    pub fn drop_x(&mut self) {
        if !self.input.is_empty() {
            self.input.clear();
            return;
        }
        self.stack.pop();
    }

    fn commit(&mut self) {
        self.error = None;
        if !self.input.is_empty() {
            self.stack.push(parse_number(&self.input, 10));
            self.input.clear();
        }
    }

    fn finish(&mut self, r: Calc<Dec>, restore: Vec<Dec>) {
        match r {
            Ok(v) => self.stack.push(v),
            Err(e) => {
                self.stack.extend(restore);
                self.error = Some(e);
            }
        }
    }
}

impl Default for Rpn {
    fn default() -> Self {
        Rpn::new()
    }
}
