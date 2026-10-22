#!/usr/bin/env sh
set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
PYTHON=${PYTHON:-python3}
VENV=${VENV:-"$ROOT/.venv"}
BASHRC=${BASHRC:-"$HOME/.bashrc"}
PATH_LINE="export PATH=\"$VENV/bin:\$PATH\""

printf '[install] root %s\n' "$ROOT"
printf '[install] venv %s\n' "$VENV"

"$PYTHON" -m venv "$VENV"
"$VENV/bin/python" -m pip install -e "$ROOT/core" -e "$ROOT/storage" -e "$ROOT/cli" -e "$ROOT/agent"

"$VENV/bin/ungit" --help >/dev/null
"$VENV/bin/ungit-core" --help >/dev/null
"$VENV/bin/ungit-agent" --help >/dev/null

touch "$BASHRC"
if grep -Fqx "$PATH_LINE" "$BASHRC"; then
  printf '[install] PATH already in %s\n' "$BASHRC"
else
  {
    printf '\n'
    printf '# Ungit CLI\n'
    printf '%s\n' "$PATH_LINE"
  } >> "$BASHRC"
  printf '[install] PATH added to %s\n' "$BASHRC"
fi

printf '[install] ok\n'
printf '[install] run now: %s/bin/ungit --help\n' "$VENV"
printf '[install] new bash: ungit --help\n'
printf '[install] current shell: . %s\n' "$BASHRC"
