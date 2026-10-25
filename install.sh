#!/usr/bin/env bash
# Install Exodus on this Mac or Linux computer.
#
# From anywhere (downloads Exodus to ~/exodus, or $EXODUS_DIR):
#   curl -fsSL https://raw.githubusercontent.com/JairoTheGyro/Exodus/main/install.sh | bash
# From an Exodus folder you already have:
#   ./install.sh
#
# Extra options are passed to scripts/install.py, for example:
#   ./install.sh --dry-run      only show what would happen
#   ./install.sh --port 7020    use another port
# Safe to run again. See docs/INSTALL.md.
set -euo pipefail

REPO_URL="https://github.com/JairoTheGyro/Exodus.git"
TARGET_DIR="${EXODUS_DIR:-$HOME/exodus}"

say() { printf '%s\n' "$*"; }
stop() { say "Install stopped: $*" >&2; exit 1; }

case "$(uname -s)" in
  Darwin)
    command -v git >/dev/null 2>&1 || stop "git is missing. Run: xcode-select --install, then run this again."
    command -v python3 >/dev/null 2>&1 || stop "python3 is missing. Run: xcode-select --install, then run this again."
    command -v docker >/dev/null 2>&1 || stop "Docker is missing. Install Docker Desktop (docker.com), start it, then run this again." ;;
  Linux)
    command -v git >/dev/null 2>&1 || stop "git is missing. On Ubuntu: sudo apt install git"
    command -v python3 >/dev/null 2>&1 || stop "python3 is missing. On Ubuntu: sudo apt install python3"
    command -v docker >/dev/null 2>&1 || stop "Docker is missing. Install Docker Engine (docs.docker.com → Install), then run this again." ;;
  *)
    stop "This installer works on macOS and Linux. On Windows, see docs/HOME_SERVER.md." ;;
esac

# Inside an Exodus folder? Use it. Otherwise download Exodus first.
script_dir=""
if [ -n "${BASH_SOURCE[0]:-}" ] && [ -f "${BASH_SOURCE[0]}" ]; then
  script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
fi
if [ -n "$script_dir" ] && [ -f "$script_dir/scripts/install.py" ]; then
  root="$script_dir"
elif [ -f "$TARGET_DIR/scripts/install.py" ]; then
  root="$TARGET_DIR"
  say "Using the Exodus folder at $root."
elif [ -e "$TARGET_DIR" ]; then
  stop "$TARGET_DIR already exists but isn't an Exodus folder. Move it, or set EXODUS_DIR to another folder."
else
  say "Downloading Exodus to $TARGET_DIR…"
  git clone "$REPO_URL" "$TARGET_DIR"
  root="$TARGET_DIR"
fi

cd "$root"
exec python3 scripts/install.py "$@"
