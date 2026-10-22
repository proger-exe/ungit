#!/usr/bin/env sh
set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
PYTHON=${PYTHON:-python3}
VENV=${VENV:-"$ROOT/.venv"}
RC_FILE=${RC_FILE:-${BASHRC:-}}
if [ -z "$RC_FILE" ]; then
  case "${SHELL:-}" in
    */zsh) RC_FILE="${ZDOTDIR:-$HOME}/.zshrc" ;;
    *) RC_FILE="$HOME/.bashrc" ;;
  esac
fi

"$PYTHON" -c 'import sys; sys.exit("Python 3.12+ is required" if sys.version_info < (3, 12) else 0)'
PATH_LINE=$("$PYTHON" -c 'import shlex, sys; print("export PATH=" + shlex.quote(sys.argv[1]) + ":\"$PATH\"")' "$VENV/bin")

printf '[install] root %s\n' "$ROOT"
printf '[install] venv %s\n' "$VENV"

"$PYTHON" -m venv "$VENV"
"$VENV/bin/python" -m pip install -e "$ROOT/core" -e "$ROOT/storage" -e "$ROOT/cli" -e "$ROOT/agent"

"$VENV/bin/ungit" --help >/dev/null
"$VENV/bin/ungit-core" --help >/dev/null
"$VENV/bin/ungit-agent" --help >/dev/null

mkdir -p "$(dirname -- "$RC_FILE")"
touch "$RC_FILE"
if grep -Fqx "$PATH_LINE" "$RC_FILE"; then
  printf '[install] PATH already in %s\n' "$RC_FILE"
else
  {
    printf '\n'
    printf '# Ungit CLI\n'
    printf '%s\n' "$PATH_LINE"
  } >> "$RC_FILE"
  printf '[install] PATH added to %s\n' "$RC_FILE"
fi

printf '[install] ok\n'
printf '[install] run now: %s/bin/ungit --help\n' "$VENV"
printf '[install] open a new terminal, or add the venv bin directory to PATH\n'
