r"""Calculator tool window (`static/js/calculator/`).

Every expected value below was captured from macOS Calculator 12.0 by typing
the same keys into the real app (see the probe list in the reconstruction
spec): precedence, repeated `=`, the iOS-style percent rule, exact decimal
arithmetic, `Undefined` for division by zero and the display's rounding and
e-notation thresholds. Also covers Programmer arithmetic, RPN, unit conversion
and the lazy-panel wiring (panels.js registration, offline precache, sidebar
entry and the Docker override mounts that let the running Exodus serve it).
"""

import json
import re
import shutil
import subprocess
import textwrap
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parent.parent
_CALC_DIR = _REPO / "static" / "js" / "calculator"
_ENGINE = (_CALC_DIR / "engine.js").as_posix()
_DECIMAL = (_CALC_DIR / "decimal.js").as_posix()
_UNITS = (_CALC_DIR / "units.js").as_posix()

_needs_node = pytest.mark.skipif(not shutil.which("node"), reason="node binary not on PATH")


def _run(js: str):
    proc = subprocess.run(
        ["node", "--input-type=module"],
        input=textwrap.dedent(js), capture_output=True, text=True, cwd=str(_REPO), timeout=30,
    )
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout.strip())


_DRIVER = f"""
const E = await import('{_ENGINE}');
const fmt = new E.NumberFormat({{ group: ',', decimal: '.' }});
function run(keys) {{
  const c = new E.AlgebraicCalculator('decimal');
  const act = {{
    '.': () => c.inputPoint(), '+': () => c.inputOperator('add'), '-': () => c.inputOperator('sub'),
    '*': () => c.inputOperator('mul'), '/': () => c.inputOperator('div'), '^': () => c.inputOperator('pow'),
    '%': () => c.applyPostfix('pct'), '!': () => c.applyPostfix('fact'), '(': () => c.openParen(),
    ')': () => c.closeParen(), '=': () => c.equals(), 's': () => c.applyFunction('sin'),
    'r': () => c.applyFunction('sqrt'), 'n': () => c.toggleSign(), '<': () => c.backspace(),
  }};
  for (const ch of keys) {{ if (/[0-9]/.test(ch)) c.inputDigit(ch); else act[ch](); }}
  if (c.evaluated) return [E.plainText(E.render(c.evaluated, fmt)), c.error ? c.error.message : fmt.format(c.result)];
  return ['', E.plainText(E.render(c.tokens, fmt))];
}}
"""

# keys, grey expression line, main display — all observed in Calculator 12.0
_PROBES = [
    ("12+3*4", "", "12+3×4"),
    ("12+3*4=", "12+3×4", "24"),
    ("2+3%", "", "2+3%"),
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
    ("123456.789*1=", "123,456.789×1", "123,456.789"),
    ("1.23456789123*1=", "1.23456789123×1", "1.23456789"),
    ("5+=", "", "5+"),
    ("n5", "", "5"),
    ("2+3=<", "", ""),
    # Scientific (degrees by default)
    ("30s", "", "sin(30)"),
    ("30s=", "sin(30)", "0.5"),
    ("2^10=", "210", "1,024"),          # rendered 2¹⁰; superscript flattened
    ("5!=", "5!", "120"),
    ("2r", "", "√(2)"),
    ("2r=", "√(2)", "1.41421356"),
    ("2*(3+4", "", "2×(3+4"),
    ("2*(3+4=", "2×(3+4)", "14"),
    ("180s=", "sin(180)", "0"),
]


@_needs_node
def test_observed_keystroke_probes():
    out = _run(_DRIVER + f"console.log(JSON.stringify({json.dumps([p[0] for p in _PROBES])}.map(run)));")
    got = {keys: tuple(res) for (keys, _, _), res in zip(_PROBES, out)}
    want = {keys: (expr, disp) for keys, expr, disp in _PROBES}
    assert got == want


@_needs_node
def test_superscripts_and_implicit_multiply():
    out = _run(f"""
        const E = await import('{_ENGINE}');
        const fmt = new E.NumberFormat({{ group: ',', decimal: '.' }});
        const c = new E.AlgebraicCalculator();
        c.inputDigit('2'); c.inputOperator('pow'); c.inputDigit('1'); c.inputDigit('0');
        const pow = E.render(c.tokens, fmt);
        // Observed: 3, 2nd 2ˣ, 8 → "2³×8" = 64
        const d = new E.AlgebraicCalculator();
        d.inputDigit('3'); d.applyFunction('twoPow'); d.inputDigit('8');
        const line = E.plainText(E.render(d.tokens, fmt));
        d.equals();
        const r = new E.AlgebraicCalculator(); r.angle = 'rad';
        r.inputConstant('pi'); r.applyFunction('cos'); r.equals();
        console.log(JSON.stringify({{ pow, line, val: d.result.toString(), cosPi: r.result.toString() }}));
    """)
    assert out["pow"] == [{"text": "2", "level": 0, "italic": False}, {"text": "10", "level": 1, "italic": False}]
    assert out["line"] == "23×8"
    assert out["val"] == "64"
    assert out["cosPi"] == "-1"


@_needs_node
def test_programmer_mode():
    out = _run(f"""
        const E = await import('{_ENGINE}');
        const fmt = new E.NumberFormat();
        const p = new E.AlgebraicCalculator('programmer'); p.base = 16;
        p.inputDigit('4'); p.inputDigit('1'); p.inputOperator('add'); p.inputDigit('1');
        const line = E.plainText(E.render(p.tokens, fmt, {{ showsBase: true }}));
        p.equals();
        const octal = new E.AlgebraicCalculator('programmer'); octal.base = 8; octal.inputDigit('9');
        console.log(JSON.stringify({{
          line, result: p.intResult.toString(16),
          flip8: E.intUnary('flip8', 0xABCDn).toString(16), flip16: E.intUnary('flip16', 0xABCD1234n).toString(16),
          rol: E.intUnary('rol', BigInt.asIntN(64, 0x8000000000000001n)).toString(), not0: E.intUnary('not', 0n).toString(),
          rejected: octal.tokens.length, hexNeg: E.integerString(-1n, 16),
        }}));
    """)
    assert out == {
        "line": "4116+116", "result": "42", "flip8": "cdab", "flip16": "1234abcd",
        "rol": "3", "not0": "-1", "rejected": 0, "hexNeg": "FFFFFFFFFFFFFFFF",
    }


@_needs_node
def test_rpn_stack():
    out = _run(f"""
        const E = await import('{_ENGINE}');
        const r = new E.RPNCalculator();
        r.inputDigit('3'); r.enter(); r.inputDigit('4'); r.enter(); r.inputDigit('5');
        const rows = r.rows.map(x => x.kind === 'value' ? x.value.toString() : x.text);
        r.binary('mul'); r.binary('add');
        const s = new E.RPNCalculator();
        for (const d of ['1', '2', '3']) {{ s.inputDigit(d); s.enter(); }}
        s.swap(); const swapped = s.stack.map(String);
        s.rollDown(); const down = s.stack.map(String);
        const p = new E.RPNCalculator(); p.inputDigit('2'); p.enter(); p.inputDigit('1'); p.inputDigit('0'); p.binary('pow');
        console.log(JSON.stringify({{ rows, sum: r.stack.map(String), swapped, down, pow: p.stack.map(String) }}));
    """)
    assert out == {"rows": ["3", "4", "5"], "sum": ["23"], "swapped": ["1", "3", "2"], "down": ["2", "1", "3"], "pow": ["1024"]}


@_needs_node
def test_decimal_and_formatting():
    out = _run(f"""
        const {{ Dec }} = await import('{_DECIMAL}');
        const E = await import('{_ENGINE}');
        const fixed = new E.NumberFormat({{ group: ',', decimal: '.', places: 2 }});
        const plain = new E.NumberFormat({{ grouping: false, group: ',', decimal: '.' }});
        const comma = new E.NumberFormat({{ group: '.', decimal: ',' }});
        console.log(JSON.stringify({{
          sum: Dec.parse('0.1').add(Dec.parse('0.2')).toString(),
          third: Dec.from(1).div(3).mul(3).round(10).toString(),
          fixed: fixed.format(Dec.parse('1234.5')), zero: fixed.format(Dec.from(0)),
          plain: plain.format(Dec.from(1234567)), comma: comma.format(Dec.parse('1234.5')),
          negSci: new E.NumberFormat().format(Dec.parse('-123456789012345678901234')),
        }}));
    """)
    assert out == {
        "sum": "0.3", "third": "1", "fixed": "1,234.50", "zero": "0.00",
        "plain": "1234567", "comma": "1.234,5", "negSci": "-1.2345679e23",
    }


@_needs_node
def test_unit_conversion():
    out = _run(f"""
        const U = await import('{_UNITS}');
        const E = await import('{_ENGINE}');
        const {{ Dec }} = await import('{_DECIMAL}');
        const f = new E.NumberFormat({{ group: ',', decimal: '.' }});
        const c = (v, a, b) => f.format(U.convert(Dec.from(v), U.findUnit(a), U.findUnit(b)));
        const rates = {{ rates: {{ USD: 1, EUR: 0.9 }}, updated: 0 }};
        console.log(JSON.stringify({{
          temp: c(100, 'temperature.C', 'temperature.F'), mile: c(1, 'length.mi', 'length.km'),
          fuel: c(30, 'fuel.mpg', 'fuel.l100km'), data: c(1, 'data.GiB', 'data.MB'),
          eur: f.format(U.convert(Dec.from(100), U.findUnit('currency.USD', rates), U.findUnit('currency.EUR', rates))),
          mixed: U.convert(Dec.from(1), U.findUnit('length.m'), U.findUnit('weight.kg')),
          categories: U.CATEGORIES.length,
          everyCategoryHasUnits: U.CATEGORIES.filter(k => k !== 'Currency').every(k => U.unitsIn(k).length >= 3),
        }}));
    """)
    assert out == {
        "temp": "212", "mile": "1.609344", "fuel": "7.8404861", "data": "1,073.741824",
        "eur": "90", "mixed": None, "categories": 15, "everyCategoryHasUnits": True,
    }


def test_panel_registration_precache_and_sidebar():
    registry = (_REPO / "static" / "js" / "apps" / "registry.js").read_text()
    assert "load: () => import('../calculator/index.js')" in registry
    assert "toggle: 'toggleCalculator'" in registry
    panels = (_REPO / "static" / "js" / "panels.js").read_text()
    assert "...appLoaders()" in panels

    sw = (_REPO / "static" / "sw.js").read_text()
    for path in sorted(_CALC_DIR.iterdir()):
        assert f"'/static/js/calculator/{path.name}'" in sw, f"{path.name} missing from PANEL_PRECACHE"

    # The Tools-menu entry is built from the registry by js/apps/launcher.js.
    app = (_REPO / "static" / "app.js").read_text()
    assert "installApps(" in app


def test_docker_override_mounts_calculator_sources():
    override = (_REPO / "docker-compose.override.yml").read_text()
    for mount in (
        "./static/js/panels.js:/app/static/js/panels.js:ro",
        "./static/js/calculator:/app/static/js/calculator:ro",
        "./static/js/apps:/app/static/js/apps:ro",
        "./routes/calculator_routes.py:/app/routes/calculator_routes.py:ro",
    ):
        assert mount in override


def test_calculator_only_uses_theme_tokens_for_colour():
    css = (_CALC_DIR / "calculator.css").read_text()
    # Fixed colours are limited to white text on the accent and neutral shadows;
    # every surface comes from --panel / --fg / --red so themes apply.
    hexes = set(re.findall(r"#[0-9a-fA-F]{3,6}\b", css))
    assert hexes <= {"#fff", "#000", "#e06c75", "#ff4444", "#c0392b"}, hexes
    assert "var(--panel)" in css and "var(--fg)" in css and "var(--red" in css


def test_browser_check_regressions_stay_fixed():
    """Layout fixes found in the 2026-10-18 in-browser run of P34."""
    css = (_CALC_DIR / "calculator.css").read_text()
    js = (_CALC_DIR / "index.js").read_text()
    # sub/superscript labels need an inline wrapper: flex items ignore vertical-align
    assert "h('span.calc-key-label'" in js
    # history scrolls inside the window instead of stretching it to the list length
    assert re.search(r"\.calc-history \{\s*position: absolute;", css)
    # Scientific/Programmer shrink to the workspace and labels scale with the pane
    assert "min(674px, var(--calc-avail))" in css and "cqw" in css
    assert "function keepOnScreen()" in js
    # operator glyph colour follows the accent's contrast (Terminal's green accent)
    assert "function syncAccentInk()" in js and "var(--calc-on-accent, #fff)" in css
    # Temple keeps keys visible using Temple's own palette tokens
    assert "html.theme-temple #calculator-modal .calc-key" in css and "var(--temple-blue)" in css
    # the mode menu has a fixed width so the decimal-places row wraps
    assert re.search(r"\.calc-menu \{\s*position: fixed;\s*width: 236px;", css)
