#!/usr/bin/env python3
"""Token/cost badge for the Claude Code status line.

Reads the status line JSON payload on stdin and prints a single compact badge to
stdout. Never fails loudly: any error prints nothing and exits 0, because a
non-zero exit hides the entire status bar.

Two data sources:

  * the stdin payload, which already carries context window usage, session cost,
    duration and edited line counts;
  * the session transcript (JSONL), parsed incrementally for the numbers the
    payload does not expose - cumulative token totals, cache hit rate and
    subagent (sidechain) usage.

The transcript is parsed incrementally and cached per session, keyed by byte
offset, so a long session does not re-read megabytes on every keystroke.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import sys
import tempfile
from datetime import datetime, timezone

# Assistant entries repeat in the transcript - the same request shows up once per
# streamed content block, each copy carrying the full usage object. Summing them
# blindly overcounts by 2-3x, so every request is counted once by requestId.
DEDUP_KEYS = ("requestId", "uuid")

# Cold start guard: a huge transcript could blow the status line timeout, so only
# the tail is read on first sight and the badge is marked approximate.
COLD_START_LIMIT = 32 * 1024 * 1024
COLD_START_TAIL = 8 * 1024 * 1024

# Bounded so the cache file cannot grow without limit in a very long session.
MAX_SEEN_IDS = 50_000

# `cost` is implemented but off by default: on subscription plans it reports 0,
# and the columns it costs buy both quota windows instead - the quota is what
# actually limits the day. Add it back through CC_TOKENS_SEGMENTS.
DEFAULT_SEGMENTS = ("ctx", "quota", "tok", "cache", "sub", "lines", "api")
ALL_SEGMENTS = DEFAULT_SEGMENTS + ("cost",)
SEGMENT_ALIASES = {"limits": "quota"}

# Dropped in this order when the badge does not fit. `cache` outranks `tok`
# because a hit rate is actionable and a running total is just a scoreboard;
# `ctx` and `quota` answer "can I keep going", so they die last.
SEGMENT_PRIORITY = ("api", "lines", "sub", "tok", "cache", "cost", "quota", "ctx")

# Below this, the reset time is not worth the width it costs.
QUOTA_ALERT_PCT = 70.0

# Glyphs have an ASCII twin because Windows consoles default to cp1252, which
# cannot encode any of these. Writing them there raises UnicodeEncodeError, and
# an uncaught one exits non-zero, which hides the entire status bar.
GLYPHS_UNICODE = {"sep": "·", "quota_sep": "│", "up": "↑", "down": "↓", "approx": "~"}
GLYPHS_ASCII = {"sep": "-", "quota_sep": "|", "up": "^", "down": "v", "approx": "~"}


def glyphs() -> dict:
    if os.environ.get("CC_TOKENS_ASCII") == "1":
        return GLYPHS_ASCII
    encoding = getattr(sys.stdout, "encoding", None) or "ascii"
    try:
        "".join(GLYPHS_UNICODE.values()).encode(encoding)
    except (LookupError, UnicodeEncodeError):
        return GLYPHS_ASCII
    return GLYPHS_UNICODE


G = GLYPHS_UNICODE  # replaced in main() once the output encoding is known

C_RESET = "\033[0m"
C_DIM = "\033[2m"
C_GREEN = "\033[38;5;71m"
C_YELLOW = "\033[38;5;179m"
C_RED = "\033[38;5;167m"
C_BLUE = "\033[38;5;110m"
C_GRAY = "\033[38;5;245m"

ANSI_RE = re.compile(r"\033\[[0-9;]*m")


def config_dir() -> str:
    return os.environ.get("CLAUDE_CONFIG_DIR") or os.path.expanduser("~/.claude")


def use_color() -> bool:
    if os.environ.get("NO_COLOR"):
        return False
    return os.environ.get("CC_TOKENS_COLOR", "1") != "0"


def paint(text: str, color: str) -> str:
    if not text or not use_color():
        return text
    return f"{color}{text}{C_RESET}"


def visible_len(text: str) -> int:
    return len(ANSI_RE.sub("", text))


def fmt_tokens(n: float) -> str:
    n = int(n or 0)
    if n < 1000:
        return str(n)
    if n < 10_000:
        return f"{n / 1000:.1f}k".replace(".0k", "k")
    if n < 1_000_000:
        return f"{round(n / 1000)}k"
    return f"{n / 1_000_000:.1f}M".replace(".0M", "M")


def fmt_cost(usd: float) -> str:
    if usd >= 100:
        return f"${usd:.0f}"
    if usd >= 10:
        return f"${usd:.1f}"
    return f"${usd:.2f}"


def fmt_duration(ms: float) -> str:
    seconds = int((ms or 0) / 1000)
    if seconds < 60:
        return f"{seconds}s"
    minutes, seconds = divmod(seconds, 60)
    if minutes < 60:
        return f"{minutes}m{seconds:02d}s"
    hours, minutes = divmod(minutes, 60)
    return f"{hours}h{minutes:02d}m"


def pct_color(pct: float) -> str:
    if pct >= 85:
        return C_RED
    if pct >= 60:
        return C_YELLOW
    return C_GREEN


# --------------------------------------------------------------------------
# transcript parsing
# --------------------------------------------------------------------------

def empty_totals() -> dict:
    return {
        "input": 0,
        "cache_creation": 0,
        "cache_read": 0,
        "output": 0,
        "thinking": 0,
        "sub_input": 0,
        "sub_cache_creation": 0,
        "sub_cache_read": 0,
        "sub_output": 0,
        "requests": 0,
        "sub_requests": 0,
    }


def cache_path(session_id: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9._-]", "_", session_id or "unknown")[:120]
    return os.path.join(config_dir(), "statusline-cache", f"tokens-{safe}.json")


def load_cache(path: str) -> dict:
    try:
        with open(path, "r", encoding="utf-8") as handle:
            state = json.load(handle)
    except (OSError, ValueError):
        return {}
    if not isinstance(state, dict):
        return {}
    return state


def save_cache(path: str, state: dict) -> None:
    directory = os.path.dirname(path)
    try:
        os.makedirs(directory, exist_ok=True)
        # Atomic: two sessions can render at once, and a half-written cache would
        # be discarded on the next read anyway - but a torn file would also make
        # the totals silently restart.
        with tempfile.NamedTemporaryFile(
            "w", encoding="utf-8", dir=directory, delete=False
        ) as tmp:
            json.dump(state, tmp)
            tmp_path = tmp.name
        os.replace(tmp_path, path)
    except OSError:
        pass


def accumulate(totals: dict, usage: dict, is_sidechain: bool) -> None:
    input_tokens = int(usage.get("input_tokens") or 0)
    cache_creation = int(usage.get("cache_creation_input_tokens") or 0)
    cache_read = int(usage.get("cache_read_input_tokens") or 0)
    output_tokens = int(usage.get("output_tokens") or 0)

    if is_sidechain:
        totals["sub_input"] += input_tokens
        totals["sub_cache_creation"] += cache_creation
        totals["sub_cache_read"] += cache_read
        totals["sub_output"] += output_tokens
        totals["sub_requests"] += 1
        return

    totals["input"] += input_tokens
    totals["cache_creation"] += cache_creation
    totals["cache_read"] += cache_read
    totals["output"] += output_tokens
    totals["requests"] += 1

    details = usage.get("output_tokens_details") or {}
    totals["thinking"] += int(details.get("thinking_tokens") or 0)


def read_transcript(transcript_path: str, session_id: str) -> dict | None:
    """Return cumulative totals for the session, parsing only new bytes."""
    try:
        size = os.path.getsize(transcript_path)
    except OSError:
        return None

    path = cache_path(session_id)
    state = load_cache(path)
    totals = state.get("totals") if isinstance(state.get("totals"), dict) else None
    offset = int(state.get("offset") or 0)
    seen = state.get("seen")
    seen = list(seen) if isinstance(seen, list) else []
    partial = bool(state.get("partial"))

    # A shrunk file means the transcript was rotated or replaced; anything cached
    # about the old one is meaningless.
    if totals is None or offset > size:
        totals = empty_totals()
        offset = 0
        seen = []
        partial = False

    if offset == 0 and size > COLD_START_LIMIT:
        offset = size - COLD_START_TAIL
        partial = True

    if size > offset:
        seen_set = set(seen)
        try:
            with open(transcript_path, "rb") as handle:
                handle.seek(offset)
                chunk = handle.read(size - offset)
        except OSError:
            return None

        consumed = offset
        # A trailing partial line is left for the next run - Claude Code appends
        # to this file while the status line renders.
        lines = chunk.split(b"\n")
        tail = lines.pop() if chunk and not chunk.endswith(b"\n") else b""

        for raw in lines:
            consumed += len(raw) + 1
            if not raw.strip():
                continue
            try:
                entry = json.loads(raw.decode("utf-8", "replace"))
            except ValueError:
                continue
            if entry.get("type") != "assistant":
                continue
            usage = (entry.get("message") or {}).get("usage")
            if not isinstance(usage, dict):
                continue

            key = None
            for field in DEDUP_KEYS:
                value = entry.get(field)
                if value:
                    key = f"{field}:{value}"
                    break
            if key is None:
                continue
            if key in seen_set:
                continue
            seen_set.add(key)
            seen.append(key)

            try:
                accumulate(totals, usage, bool(entry.get("isSidechain")))
            except (TypeError, ValueError):
                # A non-numeric usage field should cost us one entry, not the
                # whole badge - this runs outside the per-segment guard.
                continue

        if offset == 0 and consumed == 0 and not tail:
            consumed = size

        if len(seen) > MAX_SEEN_IDS:
            seen = seen[-MAX_SEEN_IDS:]

        save_cache(
            path,
            {
                "offset": consumed,
                "size": size,
                "totals": totals,
                "seen": seen,
                "partial": partial,
            },
        )

    totals = dict(totals)
    totals["partial"] = partial
    return totals


# --------------------------------------------------------------------------
# segments
# --------------------------------------------------------------------------

def seg_ctx(payload: dict, totals: dict | None) -> str:
    window = payload.get("context_window")
    if not isinstance(window, dict):
        return ""
    used = window.get("total_input_tokens")
    size = window.get("context_window_size")
    pct = window.get("used_percentage")
    if used is None or not size:
        return ""
    if pct is None:
        pct = used / size * 100
    body = f"token {fmt_tokens(used)}/{fmt_tokens(size)} {pct:.0f}%"
    return paint(body, pct_color(float(pct)))


def seg_cost(payload: dict, totals: dict | None) -> str:
    cost = payload.get("cost")
    if not isinstance(cost, dict):
        return ""
    usd = cost.get("total_cost_usd")
    # Subscription sessions report 0.0 here; a permanent "$0.00" is noise.
    if not usd:
        return ""
    return paint(fmt_cost(float(usd)), C_BLUE)


def seg_tok(payload: dict, totals: dict | None) -> str:
    if not totals:
        return ""
    billed_in = totals["input"] + totals["cache_creation"] + totals["cache_read"]
    if not billed_in and not totals["output"]:
        return ""
    mark = G["approx"] if totals.get("partial") else ""
    body = (
        f"gasto {mark}{G['up']}{fmt_tokens(billed_in)}"
        f" {G['down']}{fmt_tokens(totals['output'])}"
    )
    return paint(body, C_GRAY)


def seg_cache(payload: dict, totals: dict | None) -> str:
    if not totals:
        return ""
    billed_in = totals["input"] + totals["cache_creation"] + totals["cache_read"]
    if billed_in < 1000:
        return ""
    hit = totals["cache_read"] / billed_in * 100
    # High is good here, so the thresholds are inverted relative to context usage.
    color = C_GREEN if hit >= 80 else (C_YELLOW if hit >= 50 else C_RED)
    return paint(f"cache {hit:.0f}%", color)


def seg_sub(payload: dict, totals: dict | None) -> str:
    if not totals:
        return ""
    billed_in = (
        totals["sub_input"] + totals["sub_cache_creation"] + totals["sub_cache_read"]
    )
    total = billed_in + totals["sub_output"]
    if not total:
        return ""
    return paint(f"sub {fmt_tokens(total)}", C_GRAY)


def seg_lines(payload: dict, totals: dict | None) -> str:
    cost = payload.get("cost")
    if not isinstance(cost, dict):
        return ""
    added = int(cost.get("total_lines_added") or 0)
    removed = int(cost.get("total_lines_removed") or 0)
    if not added and not removed:
        return ""
    if not use_color():
        return f"+{added}/-{removed}"
    return f"{C_GREEN}+{added}{C_RESET}{C_DIM}/{C_RESET}{C_RED}-{removed}{C_RESET}"


def seg_api(payload: dict, totals: dict | None) -> str:
    cost = payload.get("cost")
    if not isinstance(cost, dict):
        return ""
    ms = cost.get("total_api_duration_ms")
    if not ms:
        return ""
    return paint(f"api {fmt_duration(float(ms))}", C_GRAY)


def parse_reset(value) -> datetime | None:
    """`resets_at` type is not documented - accept ISO 8601, epoch s and epoch ms."""
    if value is None:
        return None
    try:
        text = str(value).strip()
        if not text:
            return None
        if isinstance(value, (int, float)) or text.replace(".", "", 1).isdigit():
            stamp = float(value if isinstance(value, (int, float)) else text)
            # No plausible reset is 5000 years out, so a value that large is ms.
            if stamp > 1e11:
                stamp /= 1000.0
            return datetime.fromtimestamp(stamp, timezone.utc)
        if text.endswith(("Z", "z")):
            text = text[:-1] + "+00:00"
        parsed = datetime.fromisoformat(text)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed
    except (ValueError, OverflowError, OSError):
        return None


def seg_quota(payload: dict, totals: dict | None) -> str:
    limits = payload.get("rate_limits")
    if not isinstance(limits, dict):
        return ""

    # Both windows are shown, each colored on its own: they expire on different
    # clocks, so the one with room to spare still tells you which limit is the
    # real ceiling today.
    windows = []
    for key, label in (("five_hour", "5h"), ("seven_day", "7d")):
        entry = limits.get(key)
        if not isinstance(entry, dict):
            continue
        pct = entry.get("used_percentage")
        if pct is None:
            continue
        windows.append((float(pct), label, entry.get("resets_at")))
    if not windows:
        return ""

    glue = f" {paint(G['quota_sep'], C_DIM)} "
    body = paint("cota", C_GRAY) + " " + glue.join(
        paint(f"{label} {pct:.0f}%", pct_color(pct)) for pct, label, _ in windows
    )

    # One reset time at most, for whichever window is actually tight.
    worst_pct, _, resets_at = max(windows, key=lambda window: window[0])
    if worst_pct >= QUOTA_ALERT_PCT:
        reset = parse_reset(resets_at)
        if reset is not None:
            remaining = (reset - datetime.now(timezone.utc)).total_seconds()
            if remaining > 0:
                body += paint(
                    f" {G['approx']}{fmt_duration(remaining * 1000)}",
                    pct_color(worst_pct),
                )
    return body


RENDERERS = {
    "ctx": seg_ctx,
    "cost": seg_cost,
    "tok": seg_tok,
    "cache": seg_cache,
    "sub": seg_sub,
    "lines": seg_lines,
    "api": seg_api,
    "quota": seg_quota,
}


def selected_segments() -> list[str]:
    raw = os.environ.get("CC_TOKENS_SEGMENTS")
    if not raw:
        return list(DEFAULT_SEGMENTS)
    names = [name.strip() for name in raw.split(",") if name.strip()]
    names = [SEGMENT_ALIASES.get(name, name) for name in names]
    return [name for name in names if name in ALL_SEGMENTS]


def available_width() -> int:
    override = os.environ.get("CC_TOKENS_WIDTH")
    if override and override.isdigit():
        return int(override)
    columns = shutil.get_terminal_size(fallback=(80, 24)).columns
    # Other badges share the line, so the whole width is never ours.
    reserve = os.environ.get("CC_TOKENS_RESERVE", "34")
    reserve = int(reserve) if reserve.isdigit() else 34
    return max(20, columns - reserve)


def join(parts: list[str]) -> str:
    """Join segments and wrap them in one bracket - never an empty `[]`."""
    if not parts:
        return ""
    glue = f" {paint(G['sep'], C_DIM)} " if use_color() else f" {G['sep']} "
    inner = glue.join(parts)
    if not use_color():
        return f"[{inner}]"
    return f"{C_DIM}[{C_RESET}{inner}{C_DIM}]{C_RESET}"


def build(payload: dict) -> str:
    transcript = payload.get("transcript_path")
    session_id = payload.get("session_id") or payload.get("sessionId") or ""

    wanted = selected_segments()
    needs_transcript = any(name in ("tok", "cache", "sub") for name in wanted)
    totals = None
    if needs_transcript and transcript:
        totals = read_transcript(os.path.expanduser(transcript), session_id)

    rendered: dict[str, str] = {}
    for name in wanted:
        try:
            value = RENDERERS[name](payload, totals)
        except Exception:
            value = ""
        if value:
            rendered[name] = value

    order = [name for name in wanted if name in rendered]
    limit = available_width()
    # Drop the least useful segments first until it fits.
    for candidate in SEGMENT_PRIORITY:
        if visible_len(join([rendered[name] for name in order])) <= limit:
            break
        if candidate in order:
            order.remove(candidate)

    return join([rendered[name] for name in order])


def report(transcript_path: str) -> int:
    """Full breakdown for one transcript - what the badge cannot fit."""
    path = os.path.expanduser(transcript_path)
    # A separate cache id so the report never disturbs the badge's incremental
    # state (and vice versa).
    totals = read_transcript(path, f"report-{os.path.basename(path)}")
    if not totals:
        print(f"could not read transcript: {path}")
        return 1

    billed_in = totals["input"] + totals["cache_creation"] + totals["cache_read"]
    sub_in = (
        totals["sub_input"] + totals["sub_cache_creation"] + totals["sub_cache_read"]
    )
    hit = (totals["cache_read"] / billed_in * 100) if billed_in else 0.0

    rows = [
        ("requests", totals["requests"]),
        ("input (fresh)", totals["input"]),
        ("input (cache write)", totals["cache_creation"]),
        ("input (cache read)", totals["cache_read"]),
        ("input (billed total)", billed_in),
        ("output", totals["output"]),
        ("  of which thinking", totals["thinking"]),
        ("cache hit rate", f"{hit:.1f}%"),
        ("subagent requests", totals["sub_requests"]),
        ("subagent input", sub_in),
        ("subagent output", totals["sub_output"]),
    ]
    if totals.get("partial"):
        print("NOTE: transcript too large for a full read - tail only, totals are a floor.")
    for label, value in rows:
        value = f"{value:,}" if isinstance(value, int) else value
        print(f"{label:<22} {value:>14}")
    return 0


def main() -> int:
    global G
    # Windows consoles hand us cp1252, which cannot encode the separators or the
    # arrows. Ask for UTF-8 first; if that is refused, fall back to ASCII twins.
    # An unencodable character raises on the way out, and a non-zero exit hides
    # the whole status bar.
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, OSError, ValueError):
        pass
    G = glyphs()

    if "--report" in sys.argv:
        index = sys.argv.index("--report")
        if index + 1 >= len(sys.argv):
            print("usage: tokens_statusline.py --report <transcript.jsonl>")
            return 1
        return report(sys.argv[index + 1])

    try:
        raw = sys.stdin.read() if not sys.stdin.isatty() else ""
        payload = json.loads(raw) if raw.strip() else {}
        if not isinstance(payload, dict):
            payload = {}
        badge = build(payload)
        if badge:
            sys.stdout.write(badge)
            sys.stdout.flush()
    except Exception:
        if os.environ.get("CC_TOKENS_DEBUG"):
            raise
        return 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
