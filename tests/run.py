#!/usr/bin/env python3
"""Test suite for the token status line badge.

    python3 tests/run.py

Runs on Linux, macOS and Windows with no dependencies beyond the standard
library, against a throwaway CLAUDE_CONFIG_DIR so the real cache is untouched.
The suite was ported from bash precisely so the Windows runner can execute it —
the badge is meant to work there, and a bash-only suite could never prove it.
"""

from __future__ import annotations

import datetime
import json
import os
import shutil
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT = os.path.join(ROOT, "scripts", "tokens_statusline.py")
FIXTURE = os.path.join(ROOT, "tests", "fixtures", "transcript.jsonl")
WINDOWS = os.name == "nt"

passed = 0
failed = 0
skipped = 0


def ok(name: str) -> None:
    global passed
    passed += 1
    print(f"  ok   {name}")


def no(name: str, expected, actual) -> None:
    global failed
    failed += 1
    print(f"  FAIL {name}")
    print(f"       expected: {expected!r}")
    print(f"       actual:   {actual!r}")


def skip(name: str, why: str) -> None:
    global skipped
    skipped += 1
    print(f"  skip {name} ({why})")


def check(name: str, expected, actual) -> None:
    ok(name) if expected == actual else no(name, expected, actual)


def contains(name: str, needle: str, haystack: str) -> None:
    ok(name) if needle in haystack else no(name, f"contains {needle!r}", haystack)


def lacks(name: str, needle: str, haystack: str) -> None:
    no(name, f"must not contain {needle!r}", haystack) if needle in haystack else ok(name)


def payload(transcript, used=93000, pct=9.3, pct5=34.0, pct7=12.0, session="test"):
    reset = (
        datetime.datetime.now(datetime.timezone.utc)
        + datetime.timedelta(hours=2, minutes=12)
    ).isoformat().replace("+00:00", "Z")
    out = {
        "session_id": session,
        "transcript_path": transcript,
        "cost": {
            "total_cost_usd": 1.23,
            "total_api_duration_ms": 72000,
            "total_lines_added": 230,
            "total_lines_removed": 14,
        },
        "context_window": {
            "total_input_tokens": used,
            "context_window_size": 1000000,
            "used_percentage": pct,
        },
    }
    if pct5 >= 0:
        out["rate_limits"] = {
            "five_hour": {"used_percentage": pct5, "resets_at": reset},
            "seven_day": {"used_percentage": pct7, "resets_at": reset},
        }
    return json.dumps(out)


def badge(stdin: str, width="400", **env_extra) -> str:
    env = dict(os.environ, NO_COLOR="1", CC_TOKENS_WIDTH=width, **env_extra)
    proc = subprocess.run(
        [sys.executable, SCRIPT],
        input=stdin,
        capture_output=True,
        text=True,
        env=env,
    )
    return proc.stdout


def run_raw(stdin: str):
    proc = subprocess.run(
        [sys.executable, SCRIPT], input=stdin, capture_output=True, text=True
    )
    return proc.stdout, proc.returncode


def totals(session: str, field: str):
    path = os.path.join(
        os.environ["CLAUDE_CONFIG_DIR"], "statusline-cache", f"tokens-{session}.json"
    )
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)["totals"][field]


def main() -> int:
    work = tempfile.mkdtemp(prefix="cc-token-statusline-tests-")
    os.environ["CLAUDE_CONFIG_DIR"] = os.path.join(work, "claude")
    os.makedirs(os.environ["CLAUDE_CONFIG_DIR"], exist_ok=True)
    try:
        return suite(work)
    finally:
        shutil.rmtree(work, ignore_errors=True)


def suite(work: str) -> int:
    print("transcript parsing")

    # Three copies of req_A, two of req_B, two of a sidechain req_S. Counting
    # every line instead of every request would inflate these by ~2.5x.
    badge(payload(FIXTURE, session="dedup"))
    check("dedup: main requests", 2, totals("dedup", "requests"))
    check("dedup: input", 15, totals("dedup", "input"))
    check("dedup: cache creation", 300, totals("dedup", "cache_creation"))
    check("dedup: cache read", 3000, totals("dedup", "cache_read"))
    check("dedup: output", 80, totals("dedup", "output"))
    check("dedup: thinking", 20, totals("dedup", "thinking"))
    check("dedup: sidechain requests", 1, totals("dedup", "sub_requests"))
    check("dedup: sidechain output", 25, totals("dedup", "sub_output"))

    # Resuming from a cached byte offset must land on the same totals as one pass.
    fixture_lines = open(FIXTURE, "rb").read()
    split = os.path.join(work, "split.jsonl")
    with open(split, "wb") as handle:
        handle.write(b"".join(fixture_lines.splitlines(keepends=True)[:4]))
    badge(payload(split, session="incr"))
    shutil.copyfile(FIXTURE, split)
    badge(payload(split, session="incr"))
    badge(payload(FIXTURE, session="once"))
    for field in ("cache_read", "output", "requests"):
        check(f"incremental == one-shot: {field}", totals("once", field), totals("incr", field))

    # Claude Code appends while the status line renders, so a half-written last
    # line must be left for the next run, not dropped or double counted.
    torn = os.path.join(work, "torn.jsonl")
    with open(torn, "wb") as handle:
        handle.write(fixture_lines[: len(fixture_lines) // 2])
    badge(payload(torn, session="torn"))
    shutil.copyfile(FIXTURE, torn)
    badge(payload(torn, session="torn"))
    check("torn line resumes cleanly", totals("once", "cache_read"), totals("torn", "cache_read"))
    check("torn line no double count", totals("once", "requests"), totals("torn", "requests"))

    # A transcript is untrusted input: one malformed entry must not take the
    # badge down with it, and nothing from it reaches the terminal unformatted.
    poisoned = os.path.join(work, "poisoned.jsonl")
    with open(poisoned, "w", encoding="utf-8") as handle:
        handle.write(open(FIXTURE, encoding="utf-8").read())
        handle.write(
            '{"type":"assistant","uuid":"p1","requestId":"req_P","message":'
            '{"usage":{"input_tokens":"\\u001b[31mnope","output_tokens":7}}}\n'
        )
        handle.write("not json at all\n")
        handle.write(
            '{"type":"assistant","uuid":"p2","requestId":"req_Q","message":'
            '{"usage":{"input_tokens":1,"cache_read_input_tokens":9,"output_tokens":2}}}\n'
        )
    out = badge(payload(poisoned, session="poison"))
    contains("survives a malformed usage entry", "gasto", out)
    lacks("no escape sequence leaks through", "nope", out)
    check("bad entry skipped, good one kept", 3, totals("poison", "requests"))

    print("rendering")

    out = badge(payload(FIXTURE, session="r1"))
    contains("wrapped in one bracket", "[token 93k/1M 9% \u00b7", out)
    contains("ends with bracket", "api 1m12s]", out)
    contains("quota shows both windows", "cota 5h 34% \u2502 7d 12%", out)
    lacks("no reset while quota is low", "~", out)
    lacks("cost is off by default", "1.23", out)

    out = badge(payload(FIXTURE, session="r1b"), CC_TOKENS_SEGMENTS="ctx,cost")
    contains("cost still available on request", "$1.23", out)

    out = badge(payload(FIXTURE, used=780000, pct=78, pct5=41, pct7=82, session="r2"))
    contains("both windows kept when one is tight", "cota 5h 41% \u2502 7d 82%", out)
    contains("one reset, for the tight window", "~2h1", out)
    check("only one reset shown", 1, out.count("~"))

    out = badge(payload(FIXTURE, pct5=-1, pct7=-1, session="r3"))
    lacks("quota absent without rate_limits", "cota", out)

    out = badge(payload(FIXTURE, session="r4"), width="46")
    contains("narrow keeps context first", "[token 93k/1M 9%", out)
    lacks("narrow drops api", "api", out)
    check("narrow respects width", True, len(out) <= 46)

    out = badge(payload(FIXTURE, session="r5"), CC_TOKENS_SEGMENTS="ctx,limits")
    contains("limits still aliases quota", "cota 5h 34%", out)

    print("failure modes")

    for name, stdin in (
        ("empty stdin", ""),
        ("garbage stdin", "not json"),
        ("empty payload", "{}"),
    ):
        out, code = run_raw(stdin)
        check(f"{name} prints nothing, exits 0", ("", 0), (out, code))

    out = badge(
        json.dumps(
            {
                "session_id": "missing",
                "transcript_path": os.path.join(work, "does-not-exist.jsonl"),
                "context_window": {
                    "total_input_tokens": 100,
                    "context_window_size": 1000,
                    "used_percentage": 10,
                },
                "cost": {},
            }
        )
    )
    check("missing transcript still renders context", "[token 100/1k 10%]", out)

    print("setup hook")

    hook = os.path.join(ROOT, "hooks", "setup-check.sh")
    if WINDOWS:
        # Ported to python in the next step; a bash hook cannot run here, which
        # is exactly the bug this suite exists to catch.
        skip("setup hook", "bash hook, not runnable on Windows")
    else:
        hook_dir = os.path.join(work, "hookcfg")
        os.makedirs(os.path.join(hook_dir, "hooks"), exist_ok=True)
        env = dict(os.environ, CLAUDE_CONFIG_DIR=hook_dir, CLAUDE_PLUGIN_ROOT=ROOT)

        def run_hook():
            return subprocess.run(
                ["bash", hook], capture_output=True, text=True, env=env
            ).stdout

        out = run_hook()
        contains("nudges when not wired", "not wired up yet", out)
        try:
            json.loads(out)
            ok("nudge is valid json")
        except ValueError:
            no("nudge is valid json", "parses", out)

        with open(os.path.join(hook_dir, "settings.json"), "w", encoding="utf-8") as handle:
            handle.write('{"statusLine":{"command":"bash ~/.claude/hooks/tokens-statusline.sh"}}')
        shutil.copyfile(SCRIPT, os.path.join(hook_dir, "hooks", "tokens_statusline.py"))
        check("silent once wired and current", "", run_hook())

        # `plugin update` refreshes the plugin but not the copy the badge runs.
        with open(os.path.join(hook_dir, "hooks", "tokens_statusline.py"), "a", encoding="utf-8") as handle:
            handle.write("# stale\n")
        contains("warns when the installed copy drifts", "was updated but the copy", run_hook())

        open(os.path.join(hook_dir, ".cc-token-statusline-skip"), "w").close()
        check("skip marker silences everything", "", run_hook())

    print("shell syntax")
    if WINDOWS or shutil.which("bash") is None:
        skip("shell syntax", "no bash on this platform")
    else:
        for name in ("scripts/tokens-statusline.sh", "hooks/setup-check.sh", "install.sh"):
            path = os.path.join(ROOT, *name.split("/"))
            code = subprocess.run(["bash", "-n", path], capture_output=True).returncode
            ok(f"syntax {os.path.basename(name)}") if code == 0 else no(
                f"syntax {os.path.basename(name)}", "parses", "error"
            )

    print("json manifests")
    for name in (
        ".claude-plugin/plugin.json",
        ".claude-plugin/marketplace.json",
        "hooks/hooks.json",
    ):
        path = os.path.join(ROOT, *name.split("/"))
        try:
            with open(path, encoding="utf-8") as handle:
                json.load(handle)
            ok(f"valid {os.path.basename(name)}")
        except (OSError, ValueError):
            no(f"valid {os.path.basename(name)}", "parses", "error")

    print(f"\n{passed} passed, {failed} failed, {skipped} skipped")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
