#!/usr/bin/env python3
"""SessionStart hook: nudge Claude to wire, refresh or repair the badge.

Claude Code reads `statusLine` only from settings.json, so an installed plugin
cannot register a badge by itself — without this nudge the plugin installs and
silently does nothing.

Three states are worth a word, and nothing else is:

  * not wired at all                  -> offer to run the installer;
  * wired, but the installed copy is  -> offer to refresh it, because
    older than the plugin's              `plugin update` does not reach it;
  * wired through the bash entry      -> offer to rewire, because that path
    point on a machine without bash      exits non-zero and hides the whole
                                         status bar.

Silence it permanently with:  touch ~/.claude/.cc-token-statusline-skip
"""

from __future__ import annotations

import filecmp
import json
import os
import re
import shutil
import sys

BADGE_NAMES = ("tokens-statusline.sh", "tokens_statusline.py", "statusline_chain.py")
SKIP_MARKER = ".cc-token-statusline-skip"


def config_dir() -> str:
    return os.environ.get("CLAUDE_CONFIG_DIR") or os.path.expanduser("~/.claude")


def emit(message: str) -> None:
    json.dump(
        {
            "hookSpecificOutput": {
                "hookEventName": "SessionStart",
                "additionalContext": message,
            }
        },
        sys.stdout,
    )


def wiring_files(cfg: str) -> list[str]:
    return [
        os.path.join(cfg, "settings.json"),
        os.path.join(cfg, "settings.local.json"),
        os.path.join(cfg, "hooks", "combined-statusline.sh"),
    ]


def find_wiring(cfg: str) -> str | None:
    """Return the text of the file that wires the badge up, if any."""
    for path in wiring_files(cfg):
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as handle:
                text = handle.read()
        except OSError:
            continue
        if any(name in text for name in BADGE_NAMES):
            return text
    return None


def drifted_copy(installed: str, shipped: str) -> bool:
    """True when a file we installed differs from the one the plugin ships."""
    try:
        if not (os.path.isfile(installed) and os.path.isfile(shipped)):
            return False
        return not filecmp.cmp(installed, shipped, shallow=False)
    except OSError:
        return False


def missing_interpreter(wiring: str) -> str | None:
    """The interpreter the wiring names, if it is no longer there to run."""
    # The wiring is JSON on disk, so its quotes arrive escaped.
    text = wiring.replace('\\"', '"').replace("\\\\", "\\")
    match = re.search(
        r'"([^"]+)"\s+"[^"]*(?:%s)"' % "|".join(re.escape(name) for name in BADGE_NAMES),
        text,
    )
    if not match:
        return None
    command = match.group(1)
    # Only an absolute path can be judged from here. A bare name is resolved
    # against the PATH of whatever shell Claude Code renders with, which is not
    # necessarily this one, and a wrong warning is worse than no warning.
    if not os.path.isabs(command):
        return None
    return None if os.path.isfile(command) else command


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, OSError, ValueError):
        pass

    cfg = config_dir()
    root = os.environ.get("CLAUDE_PLUGIN_ROOT") or ""

    if os.path.exists(os.path.join(cfg, SKIP_MARKER)):
        return 0
    if not root:
        return 0

    wiring = find_wiring(cfg)
    installer = os.path.join(root, "scripts", "install.py").replace("\\", "/")

    if wiring is None:
        emit(
            "The cc-token-statusline plugin is installed but its status line badge is not "
            "wired up yet, so it currently shows nothing. Claude Code reads statusLine only "
            "from settings.json and a plugin cannot register one by itself. Offer to run this "
            f"once: python3 '{installer}' (use python instead of python3 on Windows). It backs "
            "up every file it edits and refuses to overwrite an unrelated statusLine. If the "
            f"user declines, tell them they can silence this notice with: touch {cfg}/{SKIP_MARKER}"
        )
        return 0

    # Wired through the bash entry point on a machine with no bash: that command
    # exits non-zero on every render, and a non-zero exit hides the whole status
    # bar, so the user loses any other badge they had too.
    if "tokens-statusline.sh" in wiring and shutil.which("bash") is None:
        emit(
            "The cc-token-statusline badge is wired through a bash entry point, but this "
            "machine has no bash on PATH. That command fails on every render, and a failing "
            "statusLine command hides the entire status bar — including any other badge. "
            f"Offer to repair it by running: python '{installer}' --replace, which rewires it "
            "to call python directly."
        )
        return 0

    # The wired command names an interpreter by absolute path. Python upgrades
    # move that path (Homebrew and pyenv carry the patch version in it), and a
    # command that cannot start exits non-zero, which hides the whole status bar.
    missing = missing_interpreter(wiring)
    if missing:
        emit(
            f"The cc-token-statusline badge is wired to run {missing}, which no longer exists "
            "on this machine - a python upgrade most likely moved it. That command fails on "
            "every render, and a failing statusLine command hides the entire status bar, "
            f"including any other badge. Offer to repair it by running: python3 '{installer}'"
        )
        return 0

    # The badge runs from a copy under the config directory, not from the
    # plugin's own files: a plugin path carries a version hash and would break on
    # every update. The trade is that `plugin update` never reaches the copy.
    # The wrapper is checked too - it is half of the install whenever the badge
    # sits behind somebody else's status line.
    drifted = any(
        drifted_copy(os.path.join(cfg, "hooks", name), os.path.join(root, "scripts", name))
        for name in ("tokens_statusline.py", "statusline_chain.py")
    )

    if drifted:
        emit(
            "The cc-token-statusline plugin was updated but the copy running in the status "
            f"line is still the old one — the badge runs from {cfg}/hooks, which plugin "
            "updates do not touch. Offer to refresh it by running: "
            f"python3 '{installer}' (python on Windows)."
        )
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        # A hook that crashes is noise in the user's session for no benefit.
        sys.exit(0)
