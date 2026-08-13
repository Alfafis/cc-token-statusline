# cc-token-statusline

Status line badge for Claude Code showing what a session is actually costing:

```
[token 93k/1M 9% · cota 5h 34% · $1.23 · gasto ↑2.4M ↓33k · cache 97% · sub 120k · +230/-14 · api 1m12s]
```

| Key | Label | Meaning | Source |
| --- | --- | --- | --- |
| `ctx` | `token` | context window used / size, colored by pressure | payload |
| `quota` | `cota` | account rate limit — the tighter of the 5h / 7d windows | payload |
| `cost` | `$` | session cost so far (hidden when the payload reports 0) | payload |
| `tok` | `gasto` | cumulative billed input / output tokens for the session | transcript |
| `cache` | `cache` | share of billed input served from cache — higher is better | transcript |
| `sub` | `sub` | tokens spent by subagents (sidechain entries) | transcript |
| `lines` | `+ -` | lines added / removed | payload |
| `api` | `api` | time spent waiting on the API | payload |

Keys are the stable identifiers used in `CC_TOKENS_SEGMENTS`; labels are only
what gets printed. `limits` is accepted as an alias for `quota`.

`cota` shows one window, not two: the one with room to spare is dead weight on a
contested line. Once a window crosses 70% the reset time is appended, since
that is the only actionable fact at that point:

```
[token 780k/1M 78% · cota 7d 82% ~2h11m · $4.10 · cache 71%]
```

The segment disappears entirely when the payload carries no `rate_limits`
(API-key accounts do not have them).

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
| `CC_TOKENS_SEGMENTS` | `ctx,quota,cost,tok,cache,sub,lines,api` | which segments, in order |
| `CC_TOKENS_WIDTH` | terminal width − reserve | hard cap on badge width |
| `CC_TOKENS_RESERVE` | `34` | columns left for other badges |
| `CC_TOKENS_COLOR` | `1` | `0` disables color (`NO_COLOR` works too) |
| `CC_TOKENS_PYTHON` | autodetected | explicit python3 path |
| `CC_TOKENS_DEBUG` | unset | raise errors instead of printing nothing |

When the badge does not fit, segments are dropped in this order:

```
api → lines → sub → tok → cache → cost → quota → ctx
```

`cache` outranks `tok` on purpose — a hit rate is actionable, a running total is
a scoreboard. `ctx` and `quota` answer "can I keep going", so they die last.

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
