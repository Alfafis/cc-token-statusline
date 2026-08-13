# cc-token-statusline

Status line badge for Claude Code showing what a session is actually costing:

```
ctx 57k/1M 6% · $1.23 · ↑1.9M ↓28k · cache 97% · sub 120k · +230/-14 · api 1m12s
```

| Segment | Meaning | Source |
| --- | --- | --- |
| `ctx` | context window used / size, colored by pressure | status line payload |
| `$` | session cost so far (hidden when the payload reports 0) | status line payload |
| `↑ ↓` | cumulative billed input / output tokens for the session | transcript |
| `cache` | share of billed input served from cache — higher is better | transcript |
| `sub` | tokens spent by subagents (sidechain entries) | transcript |
| `+ -` | lines added / removed | status line payload |
| `api` | time spent waiting on the API | status line payload |
| `limits` | 5-hour and 7-day rate limit usage (off by default) | status line payload |

## Install

```bash
./install.sh
```

It copies `tokens-statusline.sh` and `tokens_statusline.py` into `~/.claude/hooks`
and wires them up, backing up anything it edits.

If a `combined-statusline.sh` already exists, the badge is appended to its
`SCRIPTS` array. **That wrapper must forward stdin** — every number here comes
from the status line JSON payload, and the common version of the wrapper drops
it. The change is three lines:

```bash
PAYLOAD=""
[ -t 0 ] || PAYLOAD=$(cat)
# ...
badge=$(printf '%s' "$PAYLOAD" | bash "$path" 2>/dev/null)
```

If some other status line is already configured, `install.sh` stops and leaves it
alone; combine them yourself.

## Configuration

All via environment variables (settable in the `env` block of `settings.json`):

| Variable | Default | Effect |
| --- | --- | --- |
| `CC_TOKENS_SEGMENTS` | `ctx,cost,tok,cache,sub,lines,api` | which segments, in order. Add `limits` for rate limit usage. |
| `CC_TOKENS_WIDTH` | terminal width − reserve | hard cap on badge width |
| `CC_TOKENS_RESERVE` | `34` | columns left for other badges |
| `CC_TOKENS_COLOR` | `1` | `0` disables color (`NO_COLOR` works too) |
| `CC_TOKENS_PYTHON` | autodetected | explicit python3 path |
| `CC_TOKENS_DEBUG` | unset | raise errors instead of printing nothing |

When the badge does not fit, segments are dropped from the least useful end:
`api`, `lines`, `limits`, `sub`, `cache`, `tok`, `cost`, `ctx`.

## Full breakdown

```bash
python3 ~/.claude/hooks/tokens_statusline.py --report <transcript.jsonl>
```

Also available as the `/token-report` command when installed as a plugin.

## How it works

The status line command receives a JSON payload on stdin containing
`context_window`, `cost`, `model`, `rate_limits` and `transcript_path`. Context,
cost, line counts and API time come straight from it.

Cumulative tokens, cache hit rate and subagent spend are not in the payload, so
the session transcript is parsed. Two things matter there:

* **Deduplication.** Assistant entries repeat once per streamed content block,
  each copy carrying the full `usage` object. Summing them blindly overcounts by
  2–3x. Every request is counted once, keyed by `requestId`.
* **Incremental reads.** The status line re-renders constantly, so the parse is
  resumable: byte offset and running totals are cached per session under
  `~/.claude/statusline-cache/`, and only new bytes are read. A trailing partial
  line is left for the next run, since Claude Code appends while rendering.

Cold start on a transcript over 32 MB reads only the last 8 MB and marks the
token segment with `~` — the totals are then a floor, not a total.

Any error prints nothing and exits 0. A non-zero exit hides the whole status bar.

## Limitations

* `total_cost_usd` is 0 on subscription plans in some setups; the cost segment
  hides itself rather than showing a permanent `$0.00`.
* The cache directory grows one small file per session and is never pruned.
* Terminal width is read from `COLUMNS`, or from `/dev/tty` when the wrapper can
  reach it, and falls back to 80 columns otherwise — a wide terminal may drop
  segments it had room for. Set `CC_TOKENS_WIDTH` to pin it.
