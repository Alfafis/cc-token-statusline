#!/usr/bin/env python3
"""Install the token badge into the Claude Code status line.

    python3 scripts/install.py            # wire it up (python on Windows)
    python3 scripts/install.py --replace  # take over an existing statusLine
    python3 scripts/install.py --uninstall
    python3 scripts/install.py --dry-run

Copies the badge into the config directory and points `statusLine` at it. Every
file it edits is backed up first, and it refuses to clobber an unrelated
statusLine unless told to.

The wired command names this interpreter by absolute path. That sidesteps the
whole "which python" problem: `python3` does not exist on a stock Windows
install, `python` may be a Microsoft Store stub, and a bash entry point does not
exist there at all — the previous design lost the entire status bar because of it.
"""

from __future__ import annotations

import argparse
import datetime
import json
import os
import shutil
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BADGE = "tokens_statusline.py"
LEGACY_BADGE = "tokens-statusline.sh"
BADGE_NAMES = (BADGE, LEGACY_BADGE)


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


def badge_command(cfg: str) -> str:
    script = os.path.join(cfg, "hooks", BADGE).replace("\\", "/")
    python = sys.executable.replace("\\", "/")
    return f'"{python}" "{script}"'


def describe(command) -> str:
    return command if isinstance(command, str) else json.dumps(command)


def install(cfg: str, replace: bool, dry_run: bool) -> int:
    hooks = os.path.join(cfg, "hooks")
    settings_path = os.path.join(cfg, "settings.json")
    settings = load_settings(settings_path)
    existing = settings.get("statusLine")
    existing_command = (existing or {}).get("command", "") if isinstance(existing, dict) else ""

    already_ours = any(name in str(existing_command) for name in BADGE_NAMES)
    if existing and not already_ours and not replace:
        print("settings.json already has a statusLine:")
        print(f"  {describe(existing_command)}")
        print()
        print("Refusing to overwrite it. Re-run with --replace to take it over")
        print("(the previous command is saved in the backup this would create).")
        return 1

    if dry_run:
        print(f"would copy   {os.path.join(ROOT, 'scripts', BADGE)}")
        print(f"          -> {os.path.join(hooks, BADGE)}")
        print(f"would set    statusLine = {badge_command(cfg)}")
        if existing and not already_ours:
            print(f"would replace {describe(existing_command)}")
        return 0

    os.makedirs(hooks, exist_ok=True)
    shutil.copyfile(os.path.join(ROOT, "scripts", BADGE), os.path.join(hooks, BADGE))
    print(f"installed: {os.path.join(hooks, BADGE)}")

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
        settings.setdefault("_ccTokenStatuslinePrevious", existing)
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

    badge = os.path.join(cfg, "hooks", BADGE)
    if os.path.isfile(badge):
        os.remove(badge)
        print(f"removed:   {badge}")
    print()
    print(f"The token cache is left in place. To delete it: {os.path.join(cfg, 'statusline-cache')}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--replace", action="store_true", help="take over an existing statusLine")
    parser.add_argument("--uninstall", action="store_true", help="restore the previous statusLine")
    parser.add_argument("--dry-run", action="store_true", help="print what would change")
    args = parser.parse_args()

    cfg = config_dir()
    if args.uninstall:
        return uninstall(cfg, args.dry_run)
    return install(cfg, args.replace, args.dry_run)


if __name__ == "__main__":
    sys.exit(main())
