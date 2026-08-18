#!/usr/bin/env python3
"""Install the token badge into the Claude Code status line.

    python3 scripts/install.py            # wire it up (python on Windows)
    python3 scripts/install.py --replace  # take over an existing statusLine
    python3 scripts/install.py --uninstall
    python3 scripts/install.py --dry-run

Copies the badge into the config directory and points `statusLine` at it. Every
file it edits is backed up first. An existing statusLine from something else is
wrapped rather than replaced — Claude Code allows only one command, so the
previous one is run first and the badge is appended to its output. `--replace`
drops it instead, and `--uninstall` puts it back.

The wired command names this interpreter by absolute path. That sidesteps the
whole "which python" problem: `python3` does not exist on a stock Windows
install, `python` may be a Microsoft Store stub, and a bash entry point does not
exist there at all — the previous design lost the entire status bar because of it.
"""

from __future__ import annotations

import argparse
import datetime
import functools
import json
import os
import re
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)

from statusline_chain import git_bash  # noqa: E402  (needs HERE on the path first)

BADGE = "tokens_statusline.py"
CHAIN = "statusline_chain.py"
CHAIN_CONFIG = "cc-token-statusline-chain.json"
VERSION_STAMP = "cc-token-statusline-installed.json"
LEGACY_BADGE = "tokens-statusline.sh"
BADGE_NAMES = (BADGE, CHAIN, LEGACY_BADGE)
COMMAND_TOKEN = re.compile(r'"([^"]*)"|(\S+)')
# A status line command points at scripts, and a script that needs more than this
# to mention a name it runs is not one this heuristic should be guessing about.
MAX_SCRIPT_BYTES = 256 * 1024


def config_dir() -> str:
    return os.environ.get("CLAUDE_CONFIG_DIR") or os.path.expanduser("~/.claude")


def backup(path: str) -> str | None:
    if not os.path.isfile(path):
        return None
    stamp = datetime.datetime.now().strftime("%Y%m%d%H%M%S")
    target = f"{path}.bak.{stamp}"
    shutil.copyfile(path, target)
    return target


def load_settings(path: str) -> dict:
    try:
        with open(path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def save_settings(path: str, settings: dict) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(settings, handle, indent=2)
        handle.write("\n")


@functools.lru_cache(maxsize=1)
def interpreter() -> str:
    """The python this badge should be launched with, for years, not for today.

    `sys.executable` points at the real binary, which on Homebrew and pyenv
    carries the patch version in its path (.../3.13.1/...). A patch upgrade
    deletes it, the status line command then fails on every render, and a failing
    command hides the whole status bar - other badges included. A launcher on
    PATH survives that, and the badge is pure stdlib, so any modern python runs
    it. Windows is the exception: `python`/`python3` there are often Microsoft
    Store stubs that print an ad instead of running the script.
    """
    if os.name == "nt":
        return sys.executable
    for name in ("python3", "python"):
        candidate = shutil.which(name)
        if not candidate:
            continue
        try:
            probe = subprocess.run(
                [candidate, "-c", "import sys; print(sys.version_info[0], sys.version_info[1])"],
                capture_output=True, text=True, timeout=10,
            )
            major, minor = (int(part) for part in probe.stdout.split())
        except (OSError, ValueError, subprocess.SubprocessError):
            continue
        if (major, minor) >= (3, 8):
            return candidate
    return sys.executable


def command_for(cfg: str, script_name: str) -> str:
    """The command to write into settings.json, in a form its shell can run.

    Claude Code hands this string to a shell: a POSIX one on macOS and Linux, Git
    Bash on Windows when Git Bash is installed, PowerShell on Windows when it is
    not. Bash and PowerShell disagree about a line that starts with a quote —
    bash runs it, PowerShell parses it as a string expression and errors out, and
    a statusLine command that errors hides the whole status bar. Unquoted tokens
    are a program to run in both, so quotes are only spent when a path needs them.
    """
    script = os.path.join(cfg, "hooks", script_name).replace("\\", "/")
    python = interpreter().replace("\\", "/")
    if os.name != "nt":
        return f'"{python}" "{script}"'
    if " " not in python and " " not in script:
        return f"{python} {script}"
    if git_bash():
        return f'"{python}" "{script}"'
    # PowerShell's call operator, which is what makes a quoted path executable
    # there. Meaningless to bash, but bash is not what will run this machine's
    # status line: Claude Code only falls back to PowerShell when there is none.
    return f'& "{python}" "{script}"'


def badge_command(cfg: str) -> str:
    return command_for(cfg, BADGE)


def chain_command(cfg: str) -> str:
    return command_for(cfg, CHAIN)


def describe(command) -> str:
    return command if isinstance(command, str) else json.dumps(command)


def referenced_files(command: str) -> list[str]:
    """Existing files a status line command names, quoted or bare."""
    paths = []
    for quoted, bare in COMMAND_TOKEN.findall(command):
        token = (quoted or bare).strip("'")
        if not token or token.startswith("-"):
            continue
        path = os.path.expanduser(token)
        if os.path.isfile(path):
            paths.append(path)
    return paths


def runs_our_badge(command: str) -> bool:
    """True when a command that is not ours by name still ends up running it.

    A hand-rolled combiner that calls several badge scripts in a row looks like
    any other third-party status line from settings.json: the command names the
    combiner, not this badge. Wrapping it would print the badge twice — once from
    inside the combiner, once from the wrapper — so what a command *runs* has to
    be read, not just what it is called.
    """
    for path in referenced_files(command):
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as handle:
                text = handle.read(MAX_SCRIPT_BYTES)
        except OSError:
            continue
        if any(name in text for name in BADGE_NAMES):
            return True
    return False


def plugin_version() -> str:
    try:
        with open(os.path.join(ROOT, ".claude-plugin", "plugin.json"), "r", encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, ValueError):
        return ""
    version = data.get("version") if isinstance(data, dict) else None
    return version if isinstance(version, str) else ""


def stamp_version(hooks: str) -> None:
    """Record the version the copy came from, next to the copy.

    Without it the SessionStart hook can only compare bytes, which says the two
    differ and nothing about which is newer - so installing from a checkout ahead
    of the plugin cache, the normal state right after a release, made the hook
    advise a downgrade on every session.
    """
    version = plugin_version()
    if not version:
        return
    path = os.path.join(hooks, VERSION_STAMP)
    try:
        with open(path, "w", encoding="utf-8") as handle:
            json.dump({"version": version}, handle, indent=2)
    except OSError:
        return
    print(f"stamped:   {path} ({version})")


def copy_badge(hooks: str) -> None:
    os.makedirs(hooks, exist_ok=True)
    shutil.copyfile(os.path.join(ROOT, "scripts", BADGE), os.path.join(hooks, BADGE))
    print(f"installed: {os.path.join(hooks, BADGE)}")
    stamp_version(hooks)


def chained_previous(hooks: str) -> str:
    """The third-party command the installed wrapper runs before the badge."""
    try:
        with open(os.path.join(hooks, CHAIN_CONFIG), "r", encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, ValueError):
        return ""
    command = data.get("previous") if isinstance(data, dict) else None
    return command if isinstance(command, str) else ""


def install(cfg: str, replace: bool, dry_run: bool) -> int:
    hooks = os.path.join(cfg, "hooks")
    settings_path = os.path.join(cfg, "settings.json")
    settings = load_settings(settings_path)
    existing = settings.get("statusLine")
    existing_command = (existing or {}).get("command", "") if isinstance(existing, dict) else ""

    already_ours = any(name in str(existing_command) for name in BADGE_NAMES)
    # Re-running the installer is the documented way to refresh the copy after a
    # plugin update, so it must not quietly unwrap a status line it already
    # wraps: the wrapped command would vanish from settings.json and the user
    # would lose someone else's badge to an upgrade.
    wrapped = chained_previous(hooks)
    already_chained = CHAIN in str(existing_command) and bool(wrapped)
    # Someone else's status line is wrapped, not overwritten: Claude Code allows
    # exactly one command, and refusing to install was the old behavior that made
    # this plugin unusable next to ccusage, powerline and hand-rolled scripts.
    # A combiner someone wrote by hand already runs the badge; wrapping it would
    # print the badge twice. Nothing to rewire then - only the copy is refreshed,
    # which is what re-running the installer is for.
    if not already_ours and not replace and runs_our_badge(str(existing_command)):
        if dry_run:
            print(f"would copy   {os.path.join(ROOT, 'scripts', BADGE)}")
            print(f"          -> {os.path.join(hooks, BADGE)}")
            print(f"would stamp  {os.path.join(hooks, VERSION_STAMP)} ({plugin_version()})")
            print(f"would keep   {describe(existing_command)}, which already runs the badge")
            return 0
        copy_badge(hooks)
        print(f"statusLine already reaches the badge through {describe(existing_command)}, "
              "left as it is")
        return 0

    fresh_chain = bool(existing_command) and not already_ours
    chaining = (fresh_chain or already_chained) and not replace

    if dry_run:
        print(f"would copy   {os.path.join(ROOT, 'scripts', BADGE)}")
        print(f"          -> {os.path.join(hooks, BADGE)}")
        print(f"would stamp  {os.path.join(hooks, VERSION_STAMP)} ({plugin_version()})")
        if chaining:
            kept = existing_command if fresh_chain else wrapped
            print(f"would keep   {describe(kept)} and append the badge after it")
            print(f"would set    statusLine = {chain_command(cfg)}")
        else:
            if existing_command and not already_ours:
                print(f"would drop   {describe(existing_command)}")
            elif already_chained:
                print(f"would drop   {describe(wrapped)}")
            print(f"would set    statusLine = {badge_command(cfg)}")
        return 0

    copy_badge(hooks)

    if chaining:
        shutil.copyfile(os.path.join(ROOT, "scripts", CHAIN), os.path.join(hooks, CHAIN))
        if fresh_chain:
            # Only ever record a command that is not ours. Writing the wrapper's
            # own command here would make it run itself, forever.
            with open(os.path.join(hooks, CHAIN_CONFIG), "w", encoding="utf-8") as handle:
                json.dump({"previous": existing_command}, handle, indent=2)
        print(f"chaining:  {describe(existing_command if fresh_chain else wrapped)}")
        command = chain_command(cfg)
    else:
        # --replace on a wrapped install drops the wrapped command for good; a
        # stale record would resurrect it on the next refresh.
        if already_chained:
            print(f"dropped:   {describe(wrapped)}")
            for name in (CHAIN, CHAIN_CONFIG):
                path = os.path.join(hooks, name)
                if os.path.isfile(path):
                    os.remove(path)
        command = badge_command(cfg)
    if existing_command == command:
        print("statusLine already points at it, nothing to change")
        return 0

    saved = backup(settings_path)
    if saved:
        print(f"backed up: {saved}")
    if isinstance(existing, dict) and not already_ours:
        # Keep the old command inside the file rather than only in the backup, so
        # --uninstall can put it back without hunting for a timestamped copy.
        settings["_ccTokenStatuslinePrevious"] = existing
    settings["statusLine"] = {"type": "command", "command": command}
    save_settings(settings_path, settings)
    print(f"statusLine: {command}")
    return 0


def uninstall(cfg: str, dry_run: bool) -> int:
    settings_path = os.path.join(cfg, "settings.json")
    settings = load_settings(settings_path)
    current = settings.get("statusLine")
    current_command = (current or {}).get("command", "") if isinstance(current, dict) else ""
    if not any(name in str(current_command) for name in BADGE_NAMES):
        print("statusLine does not point at this badge, leaving it alone")
        return 0

    previous = settings.get("_ccTokenStatuslinePrevious")
    if dry_run:
        print("would restore" if previous else "would remove", "statusLine")
        return 0

    saved = backup(settings_path)
    if saved:
        print(f"backed up: {saved}")
    if isinstance(previous, dict):
        settings["statusLine"] = previous
        print(f"restored:  {describe(previous.get('command'))}")
    else:
        settings.pop("statusLine", None)
        print("removed statusLine")
    settings.pop("_ccTokenStatuslinePrevious", None)
    save_settings(settings_path, settings)

    for name in (BADGE, CHAIN, CHAIN_CONFIG, VERSION_STAMP, LEGACY_BADGE):
        path = os.path.join(cfg, "hooks", name)
        if os.path.isfile(path):
            os.remove(path)
            print(f"removed:   {path}")
    print()
    print(f"The token cache is left in place. To delete it: {os.path.join(cfg, 'statusline-cache')}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--replace",
        action="store_true",
        help="discard an existing statusLine instead of chaining onto it",
    )
    parser.add_argument("--uninstall", action="store_true", help="restore the previous statusLine")
    parser.add_argument("--dry-run", action="store_true", help="print what would change")
    args = parser.parse_args()

    cfg = config_dir()
    if args.uninstall:
        return uninstall(cfg, args.dry_run)
    return install(cfg, args.replace, args.dry_run)


if __name__ == "__main__":
    sys.exit(main())
