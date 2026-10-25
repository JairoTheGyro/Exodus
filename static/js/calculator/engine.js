/**
 * Calculator — loader for the Rust engine.
 *
 * Everything the Calculator computes (expression entry, exact decimal and
 * 64-bit arithmetic, RPN, memory, display formatting, expression rendering,
 * unit conversion) lives in Rust: `native/calculator/`, compiled to
 * `core.wasm` beside this file by `scripts/build_calculator_wasm.sh`. The
 * compiled file is committed, so Exodus still needs no build step to run.
 *
 * This module only moves JSON between the window and the engine: one command
 * in, one description of the whole display out, so each key press is a single
 * call. It has no DOM use, so tests drive it directly in Node.
 */

const WASM_URL = new URL('./core.wasm', import.meta.url);
const encoder = new TextEncoder();
const decoder = new TextDecoder();

let shared = null;

/**
 * Load the engine. With no argument it fetches `core.wasm` once per page and
 * reuses it; tests pass the file's bytes instead.
 */
export function loadCore(bytes) {
  if (bytes) return instantiate(bytes);
  shared ??= instantiate(null).catch((err) => { shared = null; throw err; });
  return shared;
}

async function instantiate(bytes) {
  let result;
  if (bytes) {
    result = await WebAssembly.instantiate(bytes, {});
  } else {
    const response = await fetch(WASM_URL, { credentials: 'same-origin' });
    if (!response.ok) throw new Error(`Calculator engine failed to load (${response.status})`);
    result = WebAssembly.instantiateStreaming && response.headers.get('content-type')?.includes('application/wasm')
      ? await WebAssembly.instantiateStreaming(response, {})
      : await WebAssembly.instantiate(await response.arrayBuffer(), {});
  }
  return new Core(result.instance.exports);
}

export class Core {
  constructor(exports) {
    this.x = exports;
  }

  /** Run one command object; returns the parsed reply. */
  command(cmd) {
    const x = this.x;
    const input = encoder.encode(JSON.stringify(cmd));
    const ptr = x.calc_alloc(input.length);
    new Uint8Array(x.memory.buffer, ptr, input.length).set(input);
    const packed = BigInt.asUintN(64, x.calc_command(ptr, input.length));
    x.calc_free(ptr, input.length);
    const outPtr = Number(packed >> 32n);
    const outLen = Number(packed & 0xFFFFFFFFn);
    const text = decoder.decode(new Uint8Array(x.memory.buffer, outPtr, outLen));
    x.calc_free(outPtr, outLen);
    return JSON.parse(text);
  }

  /** Settings: mode, rpn, angle, base, grouping, places, groupSep, decimalSep, convert, rates. */
  set(settings) { return this.command({ cmd: 'set', ...settings }); }
  /** A key such as ['digit', '7'], ['op', 'add'], ['fn', 'sin'], ['equals']. */
  press(key) { return this.command({ cmd: 'press', key }); }
  view() { return this.command({ cmd: 'view' }); }
  reset() { return this.command({ cmd: 'reset' }); }
  /** Insert a plain decimal string (history, memory). */
  insert(value) { return this.command({ cmd: 'insert', value }); }
  paste(text) { return this.command({ cmd: 'paste', text }); }
  toggleBit(bit) { return this.command({ cmd: 'toggleBit', bit }); }
  /** Format a stored value for history: { mode, base, trim3 }. */
  format(value, opts = {}) { return this.command({ cmd: 'format', value, ...opts }).out; }
  /** The static unit catalog: { categories, units: [{ id, category, name, abbr }] }. */
  units() { return this.command({ cmd: 'units' }).out; }
}

/** Display spans → their plain text. */
export const plainText = (spans) => (spans || []).map(s => s.text).join('');
