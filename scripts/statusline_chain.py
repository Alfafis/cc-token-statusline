#!/usr/bin/env python3
"""Run a pre-existing status line command, then append this badge.

Claude Code allows exactly one `statusLine` command, so a plugin that wants a
badge has three options: refuse to install, overwrite whatever the user already
had, or wrap it. This wraps it.

The command being wrapped is whatever was in `settings.json` before the install,
recorded in `cc-token-statusline-chain.json` next to this file. It receives the
same JSON payload on stdin that this process received, because that payload is
the only input a status line command gets.

Failure of the wrapped command is not allowed to matter: it gets a short timeout
and its errors are swallowed, so a slow or broken third-party status line costs
at most that timeout instead of taking the badge — or the whole status bar —
down with it. The timeout also has to cover the interpreter's startup, which is
free under bash and close to a second under PowerShell, so the PowerShell branch
gets an allowance on top of the budget rather than spending the budget on it.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
CONFIG = os.path.join(HERE, "cc-token-statusline-chain.json")
DEFAULT_TIMEOUT = 2.0

# The budget above is meant for the wrapped command, but the timeout covers the
# interpreter's own startup too. Under bash that costs milliseconds; PowerShell
# spends a good part of a second before it reads the command at all, even with
# `-NoProfile`, so a command that answers instantly could still be killed for
# being late. The allowance pays for the startup instead of taking it out of the
# command's share.
POWERSHELL_STARTUP_ALLOWANCE = 2.0
SHELL_VAR = "CC_TOKENS_CHAIN_SHELL"

# Where Git for Windows puts bash.exe. `C:\Windows\System32\bash.exe` is the WSL
# launcher instead: a different filesystem with different paths, which would run
# the wrapped command somewhere it cannot see the transcript.
GIT_BASH_PATHS = (
    r"C:\Program Files\Git\bin\bash.exe",
    r"C:\Program Files (x86)\Git\bin\bash.exe",
)

sys.path.insert(0, HERE)


def is_powershell(argv) -> bool:
    """True when argv runs PowerShell, judged without asking the host platform.

    `os.path.basename` splits on `\\` only on Windows, and a Windows interpreter
    path has to be recognised wherever the suite runs it.
    """
    if not argv:
        return False
    name = argv[0].replace("\\", "/").rsplit("/", 1)[-1].lower()
    return name.split(".")[0] in ("powershell", "pwsh")


def timeout(argv=None) -> float:
    """Seconds the wrapped command gets, startup of its interpreter included.

    An explicit `CC_TOKENS_CHAIN_TIMEOUT` is the whole budget and gets no
    allowance added: someone who names a number means that number.
    """
    raw = os.environ.get("CC_TOKENS_CHAIN_TIMEOUT", "")
    try:
        value = float(raw)
    except ValueError:
        value = 0.0
    if value > 0:
        return value
    if is_powershell(argv):
        return DEFAULT_TIMEOUT + POWERSHELL_STARTUP_ALLOWANCE
    return DEFAULT_TIMEOUT


def git_bash() -> str:
    """Path to a bash that shares the filesystem with Claude Code, or ""."""
    for path in GIT_BASH_PATHS:
        if os.path.isfile(path):
            return path
    local = os.environ.get("LOCALAPPDATA", "")
    if local:
        candidate = os.path.join(local, "Programs", "Git", "bin", "bash.exe")
        if os.path.isfile(candidate):
            return candidate
    git = shutil.which("git")
    if git:
        candidate = os.path.join(os.path.dirname(os.path.dirname(git)), "bin", "bash.exe")
        if os.path.isfile(candidate):
            return candidate
    found = shutil.which("bash")
    if found and "system32" not in found.replace("/", "\\").lower():
        return found
    return ""


def powershell() -> str:
    for name in ("powershell", "pwsh"):
        found = shutil.which(name)
        if found:
            return found
    return ""


def shell_argv(command: str):
    """Argv that runs `command` in the shell Claude Code itself would have used.

    Claude Code runs status line commands through Git Bash when Git Bash is
    installed and through PowerShell when it is not, so the command recorded
    from `settings.json` was written for one of those two. `shell=True` on
    Windows hands it to `cmd.exe` instead, which is neither: it does not expand
    `~`, does not know `2>/dev/null` or `$(...)`, and fails without printing
    anything, so the wrapped badge just disappears from the bar.

    Returns None when `shell=True` is the right call, which is every POSIX case:
    there Claude Code runs the command in a POSIX shell and so does this.
    """
    choice = os.environ.get(SHELL_VAR, "").strip().lower()
    if choice == "cmd":
        return None
    if os.name != "nt" and choice not in ("bash", "powershell"):
        return None
    if choice != "powershell":
        bash = git_bash()
        if bash:
            return [bash, "-c", command]
        if choice == "bash":
            return None
    shell = powershell()
    if shell:
        return [shell, "-NoProfile", "-Command", command]
    return None


def previous_command() -> str:
    try:
        with open(CONFIG, "r", encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, ValueError):
        return ""
    command = data.get("previous") if isinstance(data, dict) else None
    return command if isinstance(command, str) else ""


def run_previous(command: str, payload: str) -> str:
    if not command:
        return ""
    argv = shell_argv(command)
    try:
        proc = subprocess.run(
            command if argv is None else argv,
            shell=argv is None,
            input=payload,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout(argv),
        )
    except Exception:
        return ""
    return (proc.stdout or "").strip("\r\n")


def write(line: str) -> None:
    """Write the line, degrading rather than raising.

    Our own glyphs already fall back to ASCII when the console cannot encode
    them, but the previous status line's output passes through here untouched.
    A cp1252 stdout plus one box-drawing character in someone else's badge would
    raise on the way out, and a non-zero exit hides the whole status bar.
    """
    try:
        sys.stdout.write(line)
        sys.stdout.flush()
        return
    except UnicodeEncodeError:
        pass
    except Exception:
        return
    encoding = getattr(sys.stdout, "encoding", None) or "ascii"
    try:
        sys.stdout.write(line.encode(encoding, "replace").decode(encoding, "replace"))
        sys.stdout.flush()
    except Exception:
        pass


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, OSError, ValueError):
        pass

    try:
        raw = sys.stdin.read() if not sys.stdin.isatty() else ""
    except Exception:
        raw = ""

    parts = []
    try:
        parts.append(run_previous(previous_command(), raw))
    except Exception:
        pass

    try:
        from tokens_statusline import render

        payload = json.loads(raw) if raw.strip() else {}
        if not isinstance(payload, dict):
            payload = {}
        parts.append(render(payload))
    except Exception:
        if os.environ.get("CC_TOKENS_DEBUG"):
            raise

    line = " ".join(part for part in parts if part)
    if line:
        write(line)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        # A non-zero exit hides the entire status bar, including the command
        # this wrapper exists to preserve.
        sys.exit(0)
