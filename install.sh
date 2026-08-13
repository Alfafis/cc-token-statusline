#!/usr/bin/env bash
# Install the token badge into the Claude Code status line.
#
# Copies the badge scripts into ~/.claude/hooks and wires them up:
#
#   * no status line configured  -> point settings.json straight at the badge
#   * combined-statusline.sh set -> register the badge in its SCRIPTS array
#   * some other status line set -> print the manual step and stop
#
# Re-running is safe. Every file this touches is backed up first.

set -euo pipefail

SELF_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CLAUDE_DIR="${CLAUDE_CONFIG_DIR:-$HOME/.claude}"
HOOKS_DIR="$CLAUDE_DIR/hooks"
SETTINGS="$CLAUDE_DIR/settings.json"
COMBINED="$HOOKS_DIR/combined-statusline.sh"
BADGE="tokens-statusline.sh"

command -v python3 >/dev/null 2>&1 || {
  echo "python3 not found — the badge needs it." >&2
  exit 1
}

mkdir -p "$HOOKS_DIR"
cp "$SELF_DIR/scripts/$BADGE" "$HOOKS_DIR/$BADGE"
cp "$SELF_DIR/scripts/tokens_statusline.py" "$HOOKS_DIR/tokens_statusline.py"
chmod +x "$HOOKS_DIR/$BADGE"
echo "installed: $HOOKS_DIR/$BADGE"

backup() {
  cp "$1" "$1.bak.$(date +%Y%m%d%H%M%S)"
}

if [ -f "$COMBINED" ]; then
  if grep -q "$BADGE" "$COMBINED"; then
    echo "already registered in combined-statusline.sh"
  else
    backup "$COMBINED"
    # Append to the SCRIPTS array, matching its existing indentation.
    python3 - "$COMBINED" "$BADGE" <<'PY'
import re, sys
path, badge = sys.argv[1], sys.argv[2]
text = open(path).read()
match = re.search(r"SCRIPTS=\(\n(.*?)\n\)", text, re.S)
if not match:
    sys.exit("could not find SCRIPTS array — register the badge manually")
body = match.group(1)
indent = re.match(r"\s*", body).group(0) or "  "
text = text[:match.end(1)] + f"\n{indent}{badge}" + text[match.end(1):]
open(path, "w").write(text)
PY
    echo "registered in combined-statusline.sh"
  fi

  if ! grep -q "PAYLOAD" "$COMBINED"; then
    echo
    echo "WARNING: combined-statusline.sh does not forward stdin to its badges."
    echo "The token badge needs it — every number comes from the status line JSON."
    echo "See README.md for the three-line change."
  fi
  exit 0
fi

if [ ! -f "$SETTINGS" ]; then
  mkdir -p "$CLAUDE_DIR"
  printf '{}\n' > "$SETTINGS"
fi

backup "$SETTINGS"
python3 - "$SETTINGS" "$HOOKS_DIR/$BADGE" <<'PY'
import json, sys
path, badge = sys.argv[1], sys.argv[2]
with open(path) as handle:
    settings = json.load(handle)
existing = settings.get("statusLine")
if existing and badge not in json.dumps(existing):
    sys.exit(
        "settings.json already has a statusLine:\n  "
        + json.dumps(existing)
        + "\nCombine it manually — see README.md."
    )
settings["statusLine"] = {"type": "command", "command": f'bash "{badge}"'}
with open(path, "w") as handle:
    json.dump(settings, handle, indent=2)
    handle.write("\n")
PY
echo "wired into $SETTINGS"
