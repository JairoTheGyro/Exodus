r"""Calculator tool window (`static/js/calculator/`, engine in `native/calculator/`).

The Calculator's engine is Rust compiled to WebAssembly (`core.wasm`, committed
so Exodus needs no build step). These tests drive that real module in Node
through `engine.js`, the same loader the window uses.

Every expected value below was captured from macOS Calculator 12.0 by typing
the same keys into the real app (see the probe list in the reconstruction
spec): precedence, repeated `=`, the iOS-style percent rule, exact decimal
arithmetic, `Undefined` for division by zero and the display's rounding and
e-notation thresholds. Also covers Programmer arithmetic, RPN, unit conversion,
that `core.wasm` matches its Rust source, and the lazy-panel wiring
(registry, offline precache, Docker override mounts, the CSP that allows it).
"""

import json
import re
import shutil
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parent.parent
_CALC_DIR = _REPO / "static" / "js" / "calculator"
_ENGINE = (_CALC_DIR / "engine.js").as_posix()
_UNITS = (_CALC_DIR / "units.js").as_posix()
_WASM = (_CALC_DIR / "core.wasm").as_posix()
_CRATE = _REPO / "native" / "calculator"

_needs_node = pytest.mark.skipif(not shutil.which("node"), reason="node binary not on PATH")


def _run(js: str):
    proc = subprocess.run(
        ["node", "--input-type=module"],
        input=textwrap.dedent(js), capture_output=True, text=True, cwd=str(_REPO), timeout=30,
    )
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout.strip())


_LOAD = f"""
import fs from 'node:fs';
const {{ loadCore, plainText }} = await import('{_ENGINE}');
const core = await loadCore(fs.readFileSync('{_WASM}'));
core.set({{ groupSep: ',', decimalSep: '.' }});
"""

_KEYS = {
    ".": ["point"], "+": ["op", "add"], "-": ["op", "sub"], "*": ["op", "mul"], "/": ["op", "div"],
    "^": ["op", "pow"], "%": ["post", "pct"], "!": ["post", "fact"], "(": ["open"], ")": ["close"],
    "=": ["equals"], "s": ["fn", "sin"], "r": ["fn", "sqrt"], "n": ["sign"], "<": ["back"],
}

_DRIVER = _LOAD + f"""
const KEYS = {json.dumps(_KEYS)};
function run(keys) {{
  core.reset();
  core.set({{ groupSep: ',', decimalSep: '.' }});
  let v = core.view();
  for (const ch of keys) v = core.press(/[0-9]/.test(ch) ? ['digit', ch] : KEYS[ch]);
  return [v.expr ? plainText(v.expr) : '', v.mainText];
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
    ("2+3=<", "", "0"),
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
def test_superscripts_implicit_multiply_and_radians():
    out = _run(_LOAD + """
        let v;
        for (const k of [['digit','2'], ['op','pow'], ['digit','1'], ['digit','0']]) v = core.press(k);
        const pow = v.main;
        // Observed: 3, 2nd 2ˣ, 8 → "2³×8" = 64
        core.reset(); core.set({ groupSep: ',', decimalSep: '.' });
        for (const k of [['digit','3'], ['fn','twoPow'], ['digit','8']]) v = core.press(k);
        const line = v.mainText;
        v = core.press(['equals']);
        const val = v.mainText;
        core.reset(); core.set({ angle: 'rad' });
        core.press(['pi']); core.press(['fn', 'cos']);
        const cosPi = core.press(['equals']).mainText;
        console.log(JSON.stringify({ pow, line, val, cosPi }));
    """)
    assert out["pow"] == [{"text": "2", "level": 0, "italic": False}, {"text": "10", "level": 1, "italic": False}]
    assert out["line"] == "23×8"
    assert out["val"] == "64"
    assert out["cosPi"] == "-1"


@_needs_node
def test_programmer_mode():
    out = _run(_LOAD + """
        core.set({ mode: 'programmer', base: 16 });
        let v;
        for (const k of [['digit','4'], ['digit','1'], ['op','add'], ['digit','1']]) v = core.press(k);
        const line = v.mainText;
        v = core.press(['equals']);
        const result = v.mainText, int = v.int;
        v = core.toggleBit(0);
        const flipped = v.mainText;
        core.reset(); core.set({ mode: 'programmer', base: 16 });
        for (const d of 'ABCD') v = core.press(['digit', d]);
        v = core.press(['fn', 'flip8']); v = core.press(['equals']);
        const flip8 = v.mainText;
        core.reset(); core.set({ mode: 'programmer', base: 16 });
        core.press(['digit', 'F']); core.press(['digit', 'F']); core.press(['fn', 'not']);
        const notFF = core.press(['equals']).mainText;
        core.reset(); core.set({ mode: 'programmer', base: 8 });
        const rejected = core.press(['digit', '9']).mainText;
        core.reset(); core.set({ mode: 'programmer', base: 16 });
        const pasted = core.paste('0xff').mainText;
        console.log(JSON.stringify({ line, result, int, flipped, flip8, notFF, rejected, pasted }));
    """)
    assert out == {
        "line": "4116+116", "result": "4216", "int": "66", "flipped": "4316",
        "flip8": "CDAB16", "notFF": "FFFFFFFFFFFFFF0016", "rejected": "08", "pasted": "FF16",
    }


@_needs_node
def test_rpn_stack_and_memory():
    out = _run(_LOAD + """
        core.set({ rpn: true });
        let v;
        for (const k of [['digit','3'], ['equals'], ['digit','4'], ['equals'], ['digit','5']]) v = core.press(k);
        const rows = v.rpn;
        core.press(['op', 'mul']);
        const sum = core.press(['op', 'add']).rpn;
        core.press(['digit', '2']);
        const swapped = core.press(['swap']).rpn;
        const dropped = core.press(['drop']).rpn;
        core.reset(); core.set({ rpn: true });
        core.press(['digit','2']); core.press(['equals']); core.press(['digit','1']); core.press(['digit','0']);
        const pow = core.press(['op', 'pow']).rpn;
        core.reset();
        core.press(['digit', '7']); core.press(['m+']); core.press(['clear']);
        core.press(['digit', '3']); core.press(['op', 'add']); core.press(['mr']);
        const mem = core.press(['equals']);
        console.log(JSON.stringify({ rows, sum, swapped, dropped, pow, mem: [mem.mainText, mem.memory] }));
    """)
    assert out == {
        "rows": ["3", "4", "5"], "sum": ["", "", "23"], "swapped": ["", "2", "23"], "dropped": ["", "", "2"],
        "pow": ["", "", "1,024"], "mem": ["10", True],
    }


@_needs_node
def test_formatting_settings_and_history_format():
    out = _run(_LOAD + """
        const type = (s) => { let v; for (const ch of s) v = core.press(ch === '.' ? ['point'] : ch === '*' ? ['op','mul'] : ch === '=' ? ['equals'] : ['digit', ch]); return v; };
        core.set({ places: 2 });
        const fixed = type('1234.5*1=').mainText;
        core.reset(); core.set({ grouping: false });
        const plain = type('1234567*1=').mainText;
        core.reset(); core.set({ groupSep: '.', decimalSep: ',' });
        const comma = type('1234.5*1=').mainText;
        core.reset(); core.set({ groupSep: ',', decimalSep: '.' });
        const record = type('199.99*1=').record;
        const hist = core.format('214.98925', { trim3: true });
        const histHex = core.format('255', { mode: 'programmer', base: 16 });
        type('7.5*2=');
        const copy = core.command({ cmd: 'copy' }).out;
        console.log(JSON.stringify({ fixed, plain, comma, record: [record.result, record.mode], hist, histHex, copy }));
    """)
    assert out == {
        "fixed": "1,234.50", "plain": "1234567", "comma": "1.234,5", "record": ["199.99", "basic"],
        "hist": "214.989", "histHex": "FF", "copy": "15",
    }


@_needs_node
def test_unit_conversion():
    out = _run(_LOAD + f"""
        const U = await import('{_UNITS}');
        const catalog = core.units();
        const conv = (value, from, to) => {{
          core.reset(); core.set({{ groupSep: ',', decimalSep: '.', convert: {{ from, to }}, rates: {{ USD: 1, EUR: 0.9 }} }});
          let v = core.view();
          for (const ch of value) v = core.press(ch === '.' ? ['point'] : ['digit', ch]);
          return v.converted;
        }};
        console.log(JSON.stringify({{
          temp: conv('100', 'temperature.C', 'temperature.F'), mile: conv('1', 'length.mi', 'length.km'),
          fuel: conv('30', 'fuel.mpg', 'fuel.l100km'), data: conv('1', 'data.GiB', 'data.MB'),
          eur: conv('100', 'currency.USD', 'currency.EUR'), mixed: conv('1', 'length.m', 'weight.kg'),
          categories: catalog.categories.length,
          units: catalog.units.length,
          everyCategoryHasUnits: catalog.categories.filter(k => k !== 'Currency').every(k => U.unitsIn(k, catalog).length >= 3),
          currencyName: U.findUnit('currency.EUR', catalog, {{ rates: {{ USD: 1, EUR: 0.9 }} }}).name,
        }}));
    """)
    assert out == {
        "temp": "212", "mile": "1.609344", "fuel": "7.8404861", "data": "1,073.741824",
        "eur": "90.00", "mixed": None, "categories": 15, "units": 112, "everyCategoryHasUnits": True,
        "currencyName": "Euro",
    }


def test_core_wasm_matches_its_rust_source():
    """core.wasm is committed; a Rust change without a rebuild must fail here."""
    sys.path.insert(0, str(_REPO / "scripts"))
    try:
        from build_calculator_wasm import source_fingerprint
    finally:
        sys.path.pop(0)
    recorded = (_CRATE / "wasm-source.sha256").read_text().strip()
    assert source_fingerprint(_CRATE) == recorded, (
        "native/calculator changed: run `python3 scripts/build_calculator_wasm.py` and commit core.wasm"
    )
    assert (_CALC_DIR / "core.wasm").read_bytes()[:4] == b"\0asm"


@_needs_node
def test_core_wasm_needs_nothing_from_the_page():
    out = _run(f"""
        import fs from 'node:fs';
        const mod = await WebAssembly.compile(fs.readFileSync('{_WASM}'));
        console.log(JSON.stringify({{
          imports: WebAssembly.Module.imports(mod),
          exports: WebAssembly.Module.exports(mod).map(e => e.name).sort(),
        }}));
    """)
    assert out == {"imports": [], "exports": ["calc_alloc", "calc_command", "calc_free", "memory"]}


def test_csp_allows_webassembly_but_not_eval():
    src = (_REPO / "core" / "middleware.py").read_text()
    line = next(l for l in src.splitlines() if "script-src 'self' 'nonce-" in l)
    assert "'wasm-unsafe-eval'" in line
    assert "'unsafe-eval'" not in line.replace("'wasm-unsafe-eval'", "")


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


def test_window_updates_in_place_for_smooth_typing():
    """Speed fixes measured in the 2026-10-25 browser run (median press+redraw
    19.3 ms on the old window, 0.9 ms after): keep them from regressing."""
    js = (_CALC_DIR / "index.js").read_text()
    # Display text changes touch text nodes only; elements are rebuilt only
    # when the layout changes (standard / RPN / Convert, per mode).
    assert "function setSpans(el, spans)" in js and "el.firstChild.data = text" in js
    assert "function ensureDisplay()" in js and "function updateDisplay()" in js
    # The keypad is not part of the per-key work: AC/C updates in place and is
    # left out of the keypad's layout signature.
    assert "k.key[0] === 'clear' ? '' : k.text" in js and "btn.dataset.clear = ''" in js
    # The 64-bit grid is built once and updated bit by bit.
    assert "function buildBits()" in js and "function updateBits()" in js
    # History re-renders only when it or its number format changed.
    assert "historyDirty" in js
