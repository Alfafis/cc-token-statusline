#!/usr/bin/env bash
# SessionStart hook: tell Claude to offer the one-time wiring.
#
# Claude Code reads `statusLine` only from settings.json, so an installed plugin
# cannot register a badge by itself — without this nudge the plugin installs and
# silently does nothing. The check is self-limiting: once the badge is wired the
# hook goes quiet on its own.
#
# Silence it permanently with:  touch ~/.claude/.cc-token-statusline-skip

set -u

CLAUDE_DIR="${CLAUDE_CONFIG_DIR:-$HOME/.claude}"
ROOT="${CLAUDE_PLUGIN_ROOT:-}"
BADGE="tokens-statusline.sh"

[ -f "$CLAUDE_DIR/.cc-token-statusline-skip" ] && exit 0

WIRED=0
for candidate in \
  "$CLAUDE_DIR/settings.json" \
  "$CLAUDE_DIR/settings.local.json" \
  "$CLAUDE_DIR/hooks/combined-statusline.sh"; do
  [ -f "$candidate" ] || continue
  if grep -q "$BADGE" "$candidate" 2>/dev/null; then
    WIRED=1
    break
  fi
done

[ -n "$ROOT" ] || exit 0
# A path with a double quote or backslash would break the JSON below; stay quiet
# rather than emit something malformed into the hook channel.
case "$ROOT" in *'"'*|*'\'*) exit 0 ;; esac

if [ "$WIRED" -eq 1 ]; then
  # The status line runs a copy under ~/.claude/hooks, not the plugin's own
  # files — a versioned plugin path would break on every update. The trade is
  # that `plugin update` does not reach the copy, so drift is checked here.
  INSTALLED="$CLAUDE_DIR/hooks/tokens_statusline.py"
  SHIPPED="$ROOT/scripts/tokens_statusline.py"
  if [ -f "$INSTALLED" ] && [ -f "$SHIPPED" ] && ! cmp -s "$INSTALLED" "$SHIPPED"; then
    printf '{"hookSpecificOutput":{"hookEventName":"SessionStart","additionalContext":"%s"}}' \
      "The cc-token-statusline plugin was updated but the copy running in the status line is still the old one — the badge runs from $CLAUDE_DIR/hooks, which plugin updates do not touch. Offer to refresh it by running: bash '$ROOT/install.sh'"
  fi
  exit 0
fi

printf '{"hookSpecificOutput":{"hookEventName":"SessionStart","additionalContext":"%s"}}' \
  "The cc-token-statusline plugin is installed but its status line badge is not wired up yet, so it currently shows nothing. Claude Code reads statusLine only from settings.json and a plugin cannot register one by itself. Offer to run this once: bash '$ROOT/install.sh' — it backs up every file it edits and refuses to overwrite an unrelated statusLine. If the user declines, tell them they can silence this notice with: touch $CLAUDE_DIR/.cc-token-statusline-skip"

exit 0
