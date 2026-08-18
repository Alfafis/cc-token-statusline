#!/usr/bin/env python3
"""SessionStart hook: nudge Claude to wire, refresh or repair the badge.

Claude Code reads `statusLine` only from settings.json, so an installed plugin
cannot register a badge by itself — without this nudge the plugin installs and
silently does nothing.

Three states are worth a word, and nothing else is:

  * not wired at all                  -> offer to run the installer;
  * wired, but the plugin ships a      -> offer to refresh it, because
    newer badge than the copy runs         `plugin update` does not reach it;
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

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from install import referenced_files  # noqa: E402  (needs the script dir on the path)
from statusline_chain import git_bash  # noqa: E402

BADGE_NAMES = ("tokens-statusline.sh", "tokens_statusline.py", "statusline_chain.py")
SKIP_MARKER = ".cc-token-statusline-skip"
VERSION_STAMP = "cc-token-statusline-installed.json"
BADGE_PATTERN = "|".join(re.escape(name) for name in BADGE_NAMES)


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
    """Files that can prove the badge is wired: settings, and what they run.

    The command in settings.json may be a combiner that runs the badge among
    other scripts, in which case the badge appears nowhere in settings.json and
    only reading the referenced script settles it. The installer decides the same
    question the same way — the two must agree, or one nudges to run the other
    and the other answers that there is nothing to do.
    """
    paths = [
        os.path.join(cfg, "settings.json"),
        os.path.join(cfg, "settings.local.json"),
        os.path.join(cfg, "hooks", "combined-statusline.sh"),
    ]
    for name in ("settings.json", "settings.local.json"):
        command = statusline_command(os.path.join(cfg, name))
        paths.extend(referenced_files(command))
    return paths


def statusline_command(path: str) -> str:
    command = load_settings(path).get("statusLine")
    command = command.get("command", "") if isinstance(command, dict) else ""
    return command if isinstance(command, str) else ""


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
    """True when a file we installed differs from the one the plugin ships.

    Inequality only - which side is newer is not knowable from bytes, so this is
    the fallback for a copy installed before the version stamp existed.
    """
    try:
        if not (os.path.isfile(installed) and os.path.isfile(shipped)):
            return False
        return not filecmp.cmp(installed, shipped, shallow=False)
    except OSError:
        return False


def version_tuple(text: str) -> tuple:
    """`0.4.3` -> `(0, 4, 3)`, tolerating anything a version string may carry."""
    parts = []
    for chunk in str(text).split(".")[:3]:
        digits = "".join(ch for ch in chunk if ch.isdigit())
        parts.append(int(digits) if digits else 0)
    while len(parts) < 3:
        parts.append(0)
    return tuple(parts)


def stamped_version(cfg: str) -> str:
    """The version the installer recorded next to the copy it wrote."""
    version = load_settings(os.path.join(cfg, "hooks", VERSION_STAMP)).get("version")
    return version if isinstance(version, str) else ""


def shipped_version(root: str) -> str:
    version = load_settings(os.path.join(root, ".claude-plugin", "plugin.json")).get("version")
    return version if isinstance(version, str) else ""


def wired_interpreter(wiring: str) -> str | None:
    """The interpreter named right before the badge script, whatever the form.

    Three forms reach settings.json: quoted (`"python" "badge.py"`), bare when no
    path needs quoting, and PowerShell's call operator (`& "python" "badge.py"`)
    on a Windows box with no Git Bash. Only the middle token matters here.
    """
    # The wiring is JSON on disk, so its quotes arrive escaped.
    text = wiring.replace('\\"', '"').replace("\\\\", "\\")
    quoted = r'"([^"]+)"[^\S\n]+"[^"]*(?:%s)"' % BADGE_PATTERN
    bare = r'([^\s"\']+)[^\S\n]+([^\s"\']*(?:%s))' % BADGE_PATTERN
    for line in text.splitlines():
        if not any(name in line for name in BADGE_NAMES):
            continue
        match = re.search(quoted, line) or re.search(bare, line)
        if match:
            return match.group(1)
    return None


def missing_interpreter(wiring: str) -> str | None:
    """The interpreter the wiring names, if it is no longer there to run."""
    command = wired_interpreter(wiring)
    if not command:
        return None
    # Only an absolute path can be judged from here. A bare name is resolved
    # against the PATH of whatever shell Claude Code renders with, which is not
    # necessarily this one, and a wrong warning is worse than no warning.
    if not os.path.isabs(command):
        return None
    return None if os.path.isfile(command) else command


def wrong_shell_form(cfg: str) -> bool:
    """Windows only: the wired command suits a shell that will not run it.

    Claude Code renders the status line through Git Bash when Git Bash is
    installed and through PowerShell when it is not, and the installer writes the
    command for whichever was there at the time. Installing or removing Git after
    that flips the shell under a command written for the other one, and a command
    the shell cannot parse hides the entire status bar.
    """
    if os.name != "nt":
        return False
    for name in ("settings.json", "settings.local.json"):
        command = statusline_command(os.path.join(cfg, name))
        if not any(n in command for n in BADGE_NAMES):
            continue
        bash = bool(git_bash())
        if command.startswith("&") and bash:
            return True
        if command.startswith('"') and not bash:
            return True
    return False


def load_settings(path: str) -> dict:
    try:
        with open(path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


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
    if wrong_shell_form(cfg):
        emit(
            "The cc-token-statusline badge is wired in a form the shell that now renders it "
            "cannot parse: Claude Code uses Git Bash on Windows when Git Bash is installed and "
            "PowerShell when it is not, and installing or removing Git flips that under a "
            "command written for the other shell. A statusLine command that fails to parse "
            "hides the entire status bar, including any other badge. Offer to repair it by "
            f"running: python '{installer}'"
        )
        return 0

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
    installed = stamped_version(cfg)
    shipped = shipped_version(root)

    # With a number on both sides the direction is knowable, and only one
    # direction is worth a word. A copy ahead of the plugin is the normal state
    # right after a release is cut, and equal numbers with different bytes is a
    # local edit — nudging to overwrite either one would undo somebody's work.
    if installed and shipped:
        if version_tuple(shipped) > version_tuple(installed):
            emit(
                f"The cc-token-statusline plugin ships {shipped} but the copy running in the "
                f"status line is {installed} — the badge runs from {cfg}/hooks, which plugin "
                "updates do not touch. Offer to refresh it by running: "
                f"python3 '{installer}' (python on Windows)."
            )
        return 0

    drifted = any(
        drifted_copy(os.path.join(cfg, "hooks", name), os.path.join(root, "scripts", name))
        for name in ("tokens_statusline.py", "statusline_chain.py")
    )

    # No stamp on one of the sides, so the comparison is bytes and the message
    # must not claim a direction it cannot see.
    if drifted:
        emit(
            f"The cc-token-statusline badge runs from {cfg}/hooks, and that copy no longer "
            "matches the one the plugin ships — plugin updates do not touch it. Which of the "
            "two is newer cannot be told from here, because the copy was installed before "
            "the version stamp existed. Offer to refresh it by running: "
            f"python3 '{installer}' (python on Windows)."
        )
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        # A hook that crashes is noise in the user's session for no benefit.
        sys.exit(0)
