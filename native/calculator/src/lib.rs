//! Exodus Calculator engine (Rust, compiled to WebAssembly).
//!
//! Owns everything the Calculator window computes: expression entry, exact
//! decimal and 64-bit arithmetic, RPN, memory, display formatting, expression
//! rendering and unit conversion. The window (`static/js/calculator/index.js`)
//! only draws what this returns.
//!
//! Interface: one JSON command in, one JSON "view" of the whole display out,
//! so every key press is a single call. `static/js/calculator/engine.js` wraps
//! the raw exports (`calc_alloc`, `calc_free`, `calc_command`).

pub mod algebraic;
pub mod dec;
pub mod engine;
pub mod format;
pub mod rpn;
pub mod units;

use algebraic::{Algebraic, Kind};
use dec::Dec;
use engine::{integer_string, Angle, Constant, Func, Op, Post};
use format::{plain_text, render, NumberFormat, Span};
use rpn::{Row, Rpn};
use serde_json::{json, Value};
use std::cell::RefCell;

#[derive(Clone, Copy, PartialEq, Eq)]
pub enum Mode {
    Basic,
    Scientific,
    Programmer,
}

pub struct Core {
    mode: Mode,
    rpn_on: bool,
    algebraic: Algebraic,
    programmer: Algebraic,
    rpn: Rpn,
    /// Not persisted, like Calculator.app.
    memory: Option<Dec>,
    fmt: NumberFormat,
    convert: Option<(String, String)>,
    rates: Vec<(String, f64)>,
}

/// Append `s` as a JSON string. The per-key reply is written by hand: it is
/// small, fixed in shape and on the hot path, so no intermediate JSON tree.
fn push_json_str(out: &mut String, s: &str) {
    out.push('"');
    for ch in s.chars() {
        match ch {
            '"' => out.push_str("\\\""),
            '\\' => out.push_str("\\\\"),
            c if (c as u32) < 0x20 => out.push_str(&format!("\\u{:04x}", c as u32)),
            c => out.push(c),
        }
    }
    out.push('"');
}

fn push_spans(out: &mut String, spans: &[Span]) {
    out.push('[');
    for (i, sp) in spans.iter().enumerate() {
        if i > 0 {
            out.push(',');
        }
        out.push_str("{\"text\":");
        push_json_str(out, &sp.text);
        out.push_str(&format!(",\"level\":{},\"italic\":{}}}", sp.level, sp.italic));
    }
    out.push(']');
}

fn out_reply(out: Value) -> String {
    json!({ "out": out }).to_string()
}

fn span(text: impl Into<String>, level: i32) -> Span {
    Span { text: text.into(), level, italic: false }
}

impl Default for Core {
    fn default() -> Self {
        Core::new()
    }
}

impl Core {
    pub fn new() -> Self {
        let mut programmer = Algebraic::new(Kind::Programmer);
        programmer.base = 16;
        Core {
            mode: Mode::Basic,
            rpn_on: false,
            algebraic: Algebraic::new(Kind::Decimal),
            programmer,
            rpn: Rpn::new(),
            memory: None,
            fmt: NumberFormat::default(),
            convert: None,
            rates: Vec::new(),
        }
    }

    fn rpn_active(&self) -> bool {
        self.rpn_on && self.mode != Mode::Programmer
    }

    fn active(&self) -> &Algebraic {
        if self.mode == Mode::Programmer { &self.programmer } else { &self.algebraic }
    }

    fn active_mut(&mut self) -> &mut Algebraic {
        if self.mode == Mode::Programmer { &mut self.programmer } else { &mut self.algebraic }
    }

    fn displayed_value(&self) -> Option<Dec> {
        if self.rpn_active() { self.rpn.x() } else { self.active().current_value() }
    }

    /// Runs one JSON command. Actions return the view JSON (with `record` after a
    /// successful `=`); the `format` and `units` queries return `{ "out": … }`.
    pub fn command(&mut self, input: &str) -> String {
        let cmd: Value = match serde_json::from_str(input) {
            Ok(v) => v,
            Err(e) => return json!({ "error": format!("bad command: {}", e) }).to_string(),
        };
        let mut record: Option<String> = None;
        match cmd.get("cmd").and_then(Value::as_str).unwrap_or("view") {
            "reset" => *self = Core::new(),
            "set" => self.set(&cmd),
            "press" => {
                let key = cmd.get("key").and_then(Value::as_array);
                let part = |i: usize| key.and_then(|k| k.get(i)).and_then(Value::as_str).unwrap_or("");
                let (kind, arg) = (part(0).to_string(), part(1).to_string());
                record = self.press(&kind, &arg);
            }
            "insert" => {
                if let Some(v) = cmd.get("value").and_then(Value::as_str).and_then(Dec::parse) {
                    self.insert(&v);
                }
            }
            "paste" => self.paste(cmd.get("text").and_then(Value::as_str).unwrap_or("")),
            "toggleBit" => {
                if let Some(bit) = cmd.get("bit").and_then(Value::as_u64).filter(|b| *b < 64) {
                    let v = self.programmer.current_operand_int() ^ (1i64 << bit);
                    self.programmer.set_current_operand(v);
                }
            }
            // Queries answer without the full view (history renders call `format` per row).
            "format" => return out_reply(Value::String(self.format_value(&cmd))),
            "copy" => return out_reply(Value::String(self.copy_text())),
            "units" => {
                return out_reply(json!({
                    "categories": units::CATEGORIES,
                    "units": units::units().iter().map(|u| json!({
                        "id": u.id, "category": u.category, "name": u.name, "abbr": u.abbr,
                    })).collect::<Vec<_>>(),
                }))
            }
            _ => {}
        }
        self.view(record.as_deref())
    }

    #[doc(hidden)]
    pub fn bench_press_only(&mut self, input: &str) {
        let cmd: Value = serde_json::from_str(input).unwrap();
        let key = cmd["key"].as_array().unwrap();
        self.press(key[0].as_str().unwrap(), key.get(1).and_then(Value::as_str).unwrap_or(""));
    }

    fn set(&mut self, cmd: &Value) {
        if let Some(v) = cmd.get("grouping").and_then(Value::as_bool) {
            self.fmt.grouping = v;
        }
        if let Some(v) = cmd.get("places") {
            self.fmt.places = v.as_u64().map(|p| p.min(15) as u32);
        }
        if let Some(v) = cmd.get("groupSep").and_then(Value::as_str) {
            self.fmt.group_sep = v.to_string();
        }
        if let Some(v) = cmd.get("decimalSep").and_then(Value::as_str) {
            self.fmt.decimal_sep = v.to_string();
        }
        if let Some(v) = cmd.get("angle").and_then(Value::as_str) {
            let angle = if v == "rad" { Angle::Rad } else { Angle::Deg };
            self.algebraic.angle = angle;
            self.rpn.angle = angle;
        }
        if let Some(b) = cmd.get("base").and_then(Value::as_u64) {
            if matches!(b, 8 | 10 | 16) {
                self.programmer.convert_base(b as u32);
            }
        }
        if let Some(v) = cmd.get("rpn").and_then(Value::as_bool) {
            self.rpn_on = v;
        }
        if let Some(c) = cmd.get("convert") {
            self.convert = match (c.get("from").and_then(Value::as_str), c.get("to").and_then(Value::as_str)) {
                (Some(f), Some(t)) => Some((f.to_string(), t.to_string())),
                _ => None,
            };
        }
        if let Some(r) = cmd.get("rates").and_then(Value::as_object) {
            self.rates = r
                .iter()
                .filter_map(|(k, v)| v.as_f64().filter(|x| *x > 0.0).map(|x| (k.clone(), x)))
                .collect();
        }
        if let Some(m) = cmd.get("mode").and_then(Value::as_str) {
            let mode = match m {
                "scientific" => Mode::Scientific,
                "programmer" => Mode::Programmer,
                _ => Mode::Basic,
            };
            self.set_mode(mode);
        }
    }

    /// Carries the displayed value across decimal ↔ programmer, as Calculator does.
    fn set_mode(&mut self, mode: Mode) {
        if mode == self.mode {
            return;
        }
        let old = self.mode;
        if mode == Mode::Programmer && old != Mode::Programmer {
            let v = self.algebraic.current_value();
            self.programmer.clear_all();
            if let Some(v) = v.filter(|v| !v.is_zero()) {
                self.programmer.input_value(&v);
            }
        } else if old == Mode::Programmer && mode != Mode::Programmer {
            let v = self.programmer.current_value();
            self.algebraic.clear_all();
            if let Some(v) = v.filter(|v| !v.is_zero()) {
                self.algebraic.input_value(&v);
            }
        }
        self.mode = mode;
    }

    fn press(&mut self, kind: &str, arg: &str) -> Option<String> {
        match kind {
            "mc" => {
                self.memory = None;
                return None;
            }
            "m+" | "m-" => {
                if let Some(v) = self.displayed_value() {
                    let m = self.memory.take().unwrap_or_else(Dec::zero);
                    self.memory = Some(if kind == "m+" { m.add(&v) } else { m.sub(&v) });
                }
                return None;
            }
            _ => {}
        }
        if self.rpn_active() {
            self.press_rpn(kind, arg);
            return None;
        }
        if kind == "equals" {
            let programmer = self.mode == Mode::Programmer;
            let mode_name = match self.mode {
                Mode::Basic => "basic",
                Mode::Scientific => "scientific",
                Mode::Programmer => "programmer",
            };
            let fmt = self.fmt.clone();
            let c = self.active_mut();
            let (tokens, value) = c.equals()?;
            let base = c.base;
            let spans = render(&tokens, &fmt, programmer);
            let mut rec = String::from("{\"expr\":");
            push_spans(&mut rec, &spans);
            rec.push_str(",\"result\":");
            push_json_str(&mut rec, &value.to_plain());
            rec.push_str(&format!(",\"mode\":\"{}\",\"base\":{}}}", mode_name, base));
            return Some(rec);
        }
        let memory = self.memory.clone();
        let c = self.active_mut();
        match kind {
            "digit" => {
                if arg == "FF" {
                    c.input_digit("F");
                    c.input_digit("F");
                } else {
                    c.input_digit(arg);
                }
            }
            "00" => {
                c.input_digit("0");
                c.input_digit("0");
            }
            "point" => c.input_point(),
            "op" => {
                if let Some(op) = Op::parse(arg) {
                    c.input_operator(op)
                }
            }
            "post" => {
                if let Some(p) = Post::parse(arg) {
                    c.apply_postfix(p)
                }
            }
            "fn" => {
                if let Some(f) = Func::parse(arg) {
                    c.apply_function(f)
                }
            }
            "sign" => c.toggle_sign(),
            "back" => c.backspace(),
            "clear" => c.clear(),
            "clearAll" => c.clear_all(),
            "open" => c.open_paren(),
            "close" => c.close_paren(),
            "pi" => c.input_constant(Constant::Pi),
            "e" => c.input_constant(Constant::E),
            "rand" => c.input_constant(Constant::Value(Dec::parse(arg).unwrap_or_else(Dec::zero))),
            "mr" => {
                if let Some(m) = memory {
                    c.input_value(&m)
                }
            }
            "shl1" => c.shift_by_one(true),
            "shr1" => c.shift_by_one(false),
            _ => {}
        }
        None
    }

    fn press_rpn(&mut self, kind: &str, arg: &str) {
        let r = &mut self.rpn;
        match kind {
            "digit" => r.input_digit(arg),
            "00" => {
                r.input_digit("0");
                r.input_digit("0");
            }
            "point" => r.input_point(),
            "op" => {
                if let Some(op) = Op::parse(arg) {
                    r.binary(op)
                }
            }
            "equals" => r.enter(),
            "post" => {
                if let Some(p) = Post::parse(arg) {
                    r.postfix(p)
                }
            }
            "fn" => {
                if let Some(f) = Func::parse(arg) {
                    r.unary(f)
                }
            }
            "sign" => r.toggle_sign(),
            "back" => r.backspace(),
            "clear" | "clearAll" => r.clear(),
            "pi" => r.push(dec::pi()),
            "e" => r.push(dec::e()),
            "rand" => r.push(Dec::parse(arg).unwrap_or_else(Dec::zero)),
            "mr" => {
                if let Some(m) = self.memory.clone() {
                    self.rpn.push(m)
                }
            }
            "swap" => r.swap(),
            "rdown" => r.roll_down(),
            "rup" => r.roll_up(),
            "drop" => r.drop_x(),
            _ => {}
        }
    }

    fn insert(&mut self, v: &Dec) {
        if self.rpn_active() {
            self.rpn.push(v.clone());
        } else {
            self.active_mut().input_value(v);
        }
    }

    fn paste(&mut self, text: &str) {
        let text = text.trim();
        if text.is_empty() {
            return;
        }
        if self.mode == Mode::Programmer {
            let base = self.programmer.base;
            let digits = text.strip_prefix("0x").or_else(|| text.strip_prefix("0X")).unwrap_or(text);
            let mut v = num_bigint::BigInt::from(0u8);
            for ch in digits.chars() {
                match ch.to_digit(16) {
                    Some(d) if d < base => v = v * base + d,
                    _ => return,
                }
            }
            let n = dec::wrap_i64(&v);
            self.programmer.input_value(&Dec::from_i64(n));
            return;
        }
        let cleaned = text.replace(&self.fmt.group_sep, "").replace(&self.fmt.decimal_sep, ".");
        if let Some(v) = Dec::parse(&cleaned) {
            self.insert(&v);
        }
    }

    /// History and copy formatting. `trim3` = the sidebar's ≤ 3-decimal style
    /// (observed: 199.99+7.5% shows 214.989 there, 214.98925 on the display).
    fn format_value(&self, cmd: &Value) -> String {
        let Some(v) = cmd.get("value").and_then(Value::as_str).and_then(Dec::parse) else { return String::new() };
        if cmd.get("mode").and_then(Value::as_str) == Some("programmer") {
            let base = cmd.get("base").and_then(Value::as_u64).unwrap_or(16) as u32;
            return integer_string(v.to_i64_wrapping(), base);
        }
        let mut f = self.fmt.clone();
        if cmd.get("trim3").and_then(Value::as_bool).unwrap_or(false) && f.places.is_none() {
            f.places = Some(3);
            let text = f.format(&v);
            if text.contains('e') || !text.contains(&f.decimal_sep) {
                return text;
            }
            return text.trim_end_matches('0').trim_end_matches(f.decimal_sep.as_str()).to_string();
        }
        f.format(&v)
    }

    fn clear_label(&self) -> &'static str {
        let all_clear = if self.rpn_active() { self.rpn.shows_all_clear() } else { self.active().shows_all_clear() };
        if all_clear { "AC" } else { "C" }
    }

    fn result_spans(&self, c: &Algebraic) -> Vec<Span> {
        if let Some(e) = c.error {
            return vec![span(e.message(), 0)];
        }
        if c.kind == Kind::Programmer {
            return vec![span(integer_string(c.int_result.unwrap_or(0), c.base), 0), span(c.base.to_string(), -1)];
        }
        vec![span(self.fmt.format(&c.result.clone().unwrap_or_else(Dec::zero)), 0)]
    }

    /// Text for Copy: the displayed value without grouping (Programmer: in its base).
    fn copy_text(&self) -> String {
        match self.displayed_value() {
            None => String::new(),
            Some(d) if self.mode == Mode::Programmer => integer_string(d.to_i64_wrapping(), self.programmer.base),
            Some(d) => {
                let mut f = self.fmt.clone();
                f.grouping = false;
                f.format(&d)
            }
        }
    }

    fn converted(&self) -> Option<String> {
        let (from, to) = self.convert.as_ref()?;
        if self.mode == Mode::Programmer || self.rpn_active() {
            return None;
        }
        let f = units::find(from, &self.rates)?;
        let t = units::find(to, &self.rates)?;
        let value = self.displayed_value().unwrap_or_else(Dec::zero);
        let out = units::convert(&value, &f, &t)?;
        let mut fmt = self.fmt.clone();
        if t.category == "Currency" && fmt.places.is_none() {
            fmt.places = Some(2);
        }
        Some(fmt.format(&out))
    }

    /// The whole display as JSON: what the window draws after each command.
    fn view(&self, record: Option<&str>) -> String {
        let c = self.active();
        let shows_base = self.mode == Mode::Programmer;
        let (expr, main) = if c.showing_result() {
            (Some(render(c.evaluated.as_deref().unwrap_or(&[]), &self.fmt, shows_base)), self.result_spans(c))
        } else if !c.tokens.is_empty() {
            (None, render(&c.tokens, &self.fmt, shows_base))
        } else if shows_base {
            (None, vec![span("0", 0), span(c.base.to_string(), -1)])
        } else {
            (None, vec![span("0", 0)])
        };
        let mut out = String::with_capacity(256);
        out.push_str(&format!(
            "{{\"clear\":\"{}\",\"showingResult\":{},\"memory\":{},\"expr\":",
            self.clear_label(),
            !self.rpn_active() && c.showing_result(),
            self.memory.is_some(),
        ));
        match &expr {
            Some(e) => push_spans(&mut out, e),
            None => out.push_str("null"),
        }
        out.push_str(",\"main\":");
        push_spans(&mut out, &main);
        out.push_str(",\"mainText\":");
        push_json_str(&mut out, &plain_text(&main));

        out.push_str(",\"rpn\":");
        if self.rpn_active() {
            let rows = self.rpn.rows();
            let start = rows.len().saturating_sub(3);
            let mut texts: Vec<String> = rows[start..]
                .iter()
                .map(|r| match r {
                    Row::Value(d) => self.fmt.format(d),
                    Row::Typing(t) => self.fmt.typed(t),
                    Row::Error(e) => e.message().to_string(),
                })
                .collect();
            while texts.len() < 3 {
                texts.insert(0, String::new());
            }
            out.push('[');
            for (i, t) in texts.iter().enumerate() {
                if i > 0 {
                    out.push(',');
                }
                push_json_str(&mut out, t);
            }
            out.push(']');
        } else {
            out.push_str("null");
        }

        // Unsigned 64-bit pattern as decimal text (JS reads it with BigInt).
        if shows_base {
            out.push_str(&format!(",\"int\":\"{}\"", self.programmer.current_operand_int() as u64));
        }
        out.push_str(",\"converted\":");
        match self.converted() {
            Some(t) => push_json_str(&mut out, &t),
            None => out.push_str("null"),
        }
        out.push_str(",\"record\":");
        out.push_str(record.unwrap_or("null"));
        out.push('}');
        out
    }
}

// ── WebAssembly interface ───────────────────────────────────────────────

thread_local! {
    static CORE: RefCell<Core> = RefCell::new(Core::new());
}

/// Reserve `len` bytes for the caller to write a command into.
#[no_mangle]
pub extern "C" fn calc_alloc(len: usize) -> *mut u8 {
    let mut buf: Vec<u8> = Vec::with_capacity(len.max(1));
    let ptr = buf.as_mut_ptr();
    std::mem::forget(buf);
    ptr
}

/// Release a buffer from `calc_alloc` or a `calc_command` result.
///
/// # Safety
/// `ptr`/`cap` must come from `calc_alloc` or `calc_command` and be freed once.
#[no_mangle]
pub unsafe extern "C" fn calc_free(ptr: *mut u8, cap: usize) {
    if !ptr.is_null() {
        drop(Vec::from_raw_parts(ptr, 0, cap.max(1)));
    }
}

/// Run a UTF-8 JSON command; returns `(ptr << 32) | len` of the UTF-8 JSON reply.
///
/// # Safety
/// `ptr` must point to `len` readable bytes.
#[no_mangle]
pub unsafe extern "C" fn calc_command(ptr: *const u8, len: usize) -> u64 {
    let input = std::str::from_utf8(std::slice::from_raw_parts(ptr, len)).unwrap_or("{}");
    let reply = CORE.with(|c| c.borrow_mut().command(input));
    let mut bytes = reply.into_bytes();
    bytes.shrink_to_fit();
    let len = bytes.len();
    let mut boxed = bytes.into_boxed_slice();
    let out = boxed.as_mut_ptr();
    std::mem::forget(boxed);
    ((out as u64) << 32) | len as u64
}

// ── Behaviour tests (observed in macOS Calculator 12.0) ─────────────────

#[cfg(test)]
mod tests {
    use super::*;

    fn view(core: &Core) -> Value {
        serde_json::from_str(&core.view(None)).expect("view is valid JSON")
    }

    fn run(core: &mut Core, keys: &str) -> (String, String) {
        for ch in keys.chars() {
            let (kind, arg) = match ch {
                '0'..='9' => ("digit", ch.to_string()),
                '.' => ("point", String::new()),
                '+' => ("op", "add".into()),
                '-' => ("op", "sub".into()),
                '*' => ("op", "mul".into()),
                '/' => ("op", "div".into()),
                '^' => ("op", "pow".into()),
                '%' => ("post", "pct".into()),
                '!' => ("post", "fact".into()),
                '(' => ("open", String::new()),
                ')' => ("close", String::new()),
                '=' => ("equals", String::new()),
                's' => ("fn", "sin".into()),
                'r' => ("fn", "sqrt".into()),
                'n' => ("sign", String::new()),
                '<' => ("back", String::new()),
                _ => panic!("unknown key {}", ch),
            };
            core.press(kind, &arg);
        }
        let view = view(core);
        let expr = view["expr"].as_array().map(|a| a.iter().map(|s| s["text"].as_str().unwrap().to_string()).collect::<String>()).unwrap_or_default();
        (expr, view["mainText"].as_str().unwrap().to_string())
    }

    #[test]
    fn observed_keystroke_probes() {
        let cases: &[(&str, &str, &str)] = &[
            ("12+3*4", "", "12+3×4"),
            ("12+3*4=", "12+3×4", "24"),
            ("2+3%=", "2+3%", "2.06"),
            ("200+10%=", "200+10%", "220"),
            ("199.99+7.5%=", "199.99+7.5%", "214.98925"),
            ("50%=", "50%", "0.5"),
            ("2*3%=", "2×3%", "0.06"),
            ("1/3=", "1÷3", "0.33333333"),
            ("2/3=", "2÷3", "0.66666667"),
            ("2+3===", "8+3", "11"),
            ("1/0=", "1÷0", "Undefined"),
            ("123456789*1000000000=", "123,456,789×1,000,000,000", "123,456,789,000,000,000"),
            ("2+3=4", "", "4"),
            ("2+3=*2", "", "5×2"),
            ("-5*2=", "-5×2", "-10"),
            ("2+*3", "", "2×3"),
            (".5+.25=", "0.5+0.25", "0.75"),
            ("0.1+0.2=", "0.1+0.2", "0.3"),
            ("99999999*99999999*99999999=", "99,999,999×99,999,999×99,999,999", "9.9999997e23"),
            ("2/3*3=", "2÷3×3", "2"),
            ("1000/7=", "1,000÷7", "142.85714286"),
            ("10000000000/3=", "10,000,000,000÷3", "3,333,333,333.33333333"),
            ("99999999999999999999+1=", "99,999,999,999,999,999,999+1", "1e20"),
            ("0.000000001*0.001=", "0.000000001×0.001", "1e-12"),
            ("1.23456789123*1=", "1.23456789123×1", "1.23456789"),
            ("5+=", "", "5+"),
            ("n5", "", "5"),
            ("30s=", "sin(30)", "0.5"),
            ("2^10=", "210", "1,024"),
            ("5!=", "5!", "120"),
            ("2r=", "√(2)", "1.41421356"),
            ("2*(3+4=", "2×(3+4)", "14"),
            ("180s=", "sin(180)", "0"),
        ];
        for (keys, expr, main) in cases {
            let mut core = Core::new();
            assert_eq!(run(&mut core, keys), (expr.to_string(), main.to_string()), "keys {}", keys);
        }
    }

    #[test]
    fn programmer_hex_and_flips() {
        let mut core = Core::new();
        core.set(&json!({ "mode": "programmer", "base": 16 }));
        for k in ["4", "1"] {
            core.press("digit", k);
        }
        core.press("op", "add");
        core.press("digit", "1");
        assert_eq!(view(&core)["mainText"], "4116+116");
        core.press("equals", "");
        assert_eq!(view(&core)["mainText"], "4216");
        assert_eq!(engine::int_unary(Func::Flip8, 0xABCD), 0xCDAB);
        assert_eq!(engine::int_unary(Func::Flip16, 0xABCD1234), 0x1234ABCD);
        assert_eq!(engine::int_unary(Func::Not, 0), -1);
    }

    #[test]
    fn rpn_stack() {
        let mut core = Core::new();
        core.set(&json!({ "rpn": true }));
        core.press("digit", "3");
        core.press("equals", "");
        core.press("digit", "4");
        core.press("equals", "");
        core.press("digit", "5");
        assert_eq!(view(&core)["rpn"], json!(["3", "4", "5"]));
        core.press("op", "mul");
        core.press("op", "add");
        assert_eq!(view(&core)["rpn"], json!(["", "", "23"]));
    }

    #[test]
    fn conversion_and_commands() {
        let mut core = Core::new();
        let reply: Value = serde_json::from_str(&core.command(r#"{"cmd":"set","convert":{"from":"temperature.C","to":"temperature.F"}}"#)).unwrap();
        assert_eq!(reply["converted"], "32");
        core.command(r#"{"cmd":"press","key":["digit","1"]}"#);
        core.command(r#"{"cmd":"press","key":["digit","0"]}"#);
        let reply: Value = serde_json::from_str(&core.command(r#"{"cmd":"press","key":["digit","0"]}"#)).unwrap();
        assert_eq!(reply["converted"], "212");
        let reply: Value = serde_json::from_str(&core.command(r#"{"cmd":"set","rates":{"USD":1,"EUR":0.9},"convert":{"from":"currency.USD","to":"currency.EUR"}}"#)).unwrap();
        assert_eq!(reply["converted"], "90.00");
        let reply: Value = serde_json::from_str(&core.command(r#"{"cmd":"format","value":"214.98925","trim3":true}"#)).unwrap();
        assert_eq!(reply["out"], "214.989");
        assert!(core.command("not json").contains("bad command"));
    }
}
