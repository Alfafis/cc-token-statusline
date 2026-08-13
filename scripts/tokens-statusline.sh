#!/usr/bin/env bash
# cc-token-statusline — badge script for the Claude Code status line.
#
# Reads the status line JSON payload on stdin and prints a token/cost badge.
# Exits 0 unconditionally: a non-zero exit hides the whole status bar.
#
# Wired either directly:
#   "statusLine": { "type": "command", "command": "bash ~/.claude/hooks/tokens-statusline.sh" }
#
# or as one entry of a combined status line that forwards stdin to each badge.

set -u

SELF_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SCRIPT="$SELF_DIR/tokens_statusline.py"
[ -f "$SCRIPT" ] || SCRIPT="$SELF_DIR/../scripts/tokens_statusline.py"
[ -f "$SCRIPT" ] || exit 0

# The badge trims itself to the available width, but stdout here is a pipe, so
# the terminal size has to come from somewhere else. Claude Code owns a tty even
# though this subprocess does not inherit one.
if [ -z "${CC_TOKENS_WIDTH:-}" ] && [ -z "${COLUMNS:-}" ]; then
  # Braces so the shell's own "no such device" complaint is redirected too.
  cols=$({ stty size </dev/tty; } 2>/dev/null | cut -d' ' -f2)
  case "$cols" in
    ''|*[!0-9]*) ;;
    *) export COLUMNS="$cols" ;;
  esac
fi

PYTHON="${CC_TOKENS_PYTHON:-}"
if [ -z "$PYTHON" ]; then
  for candidate in python3 /usr/bin/python3 /opt/homebrew/bin/python3; do
    if command -v "$candidate" >/dev/null 2>&1; then
      PYTHON="$candidate"
      break
    fi
  done
fi
[ -n "$PYTHON" ] || exit 0

"$PYTHON" "$SCRIPT" 2>/dev/null || true
exit 0
