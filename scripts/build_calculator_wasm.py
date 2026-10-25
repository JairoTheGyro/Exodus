#!/usr/bin/env python3
"""Rebuild the Calculator's Rust engine into static/js/calculator/core.wasm.

Exodus serves plain files with no build step, so the compiled WebAssembly is
committed next to the JavaScript that loads it. Run this after changing
anything in native/calculator/:

    python3 scripts/build_calculator_wasm.py

Needs Rust with the WebAssembly target (`rustup target add wasm32-unknown-unknown`).
It also records a fingerprint of the Rust sources in
native/calculator/wasm-source.sha256; tests/test_calculator_js.py compares it,
so a source change without a rebuild fails the tests (no Rust needed there).
"""

from __future__ import annotations

import hashlib
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CRATE = ROOT / "native" / "calculator"
OUTPUT = ROOT / "static" / "js" / "calculator" / "core.wasm"
FINGERPRINT = CRATE / "wasm-source.sha256"
TARGET = "wasm32-unknown-unknown"


def source_fingerprint(crate: Path = CRATE) -> str:
    """SHA-256 over the crate's manifest, lockfile and Rust sources."""
    files = [crate / "Cargo.toml", crate / "Cargo.lock", *sorted((crate / "src").rglob("*.rs"))]
    digest = hashlib.sha256()
    for path in files:
        digest.update(path.relative_to(crate).as_posix().encode())
        digest.update(b"\0")
        digest.update(path.read_bytes().replace(b"\r\n", b"\n"))
        digest.update(b"\0")
    return digest.hexdigest()


def main() -> int:
    if not shutil.which("cargo"):
        print("cargo not found: install Rust from https://rustup.rs", file=sys.stderr)
        return 1
    subprocess.run(
        ["cargo", "build", "--release", "--locked", "--target", TARGET],
        cwd=CRATE, check=True,
    )
    built = CRATE / "target" / TARGET / "release" / "exodus_calculator.wasm"
    shutil.copyfile(built, OUTPUT)
    FINGERPRINT.write_text(source_fingerprint() + "\n", encoding="utf-8")
    print(f"{OUTPUT.relative_to(ROOT)}: {OUTPUT.stat().st_size:,} bytes")
    return 0


if __name__ == "__main__":
    sys.exit(main())
