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
down with it.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
CONFIG = os.path.join(HERE, "cc-token-statusline-chain.json")
DEFAULT_TIMEOUT = 2.0

sys.path.insert(0, HERE)


def timeout() -> float:
    raw = os.environ.get("CC_TOKENS_CHAIN_TIMEOUT", "")
    try:
        value = float(raw)
    except ValueError:
        return DEFAULT_TIMEOUT
    return value if value > 0 else DEFAULT_TIMEOUT


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
    try:
        proc = subprocess.run(
            command,
            shell=True,
            input=payload,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout(),
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
