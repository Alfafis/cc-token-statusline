# cc-token-statusline

[![tests](https://github.com/Alfafis/cc-token-statusline/actions/workflows/ci.yml/badge.svg)](https://github.com/Alfafis/cc-token-statusline/actions/workflows/ci.yml)

Status line badge for Claude Code showing what a session is actually costing:

```
[token 93k/1M 9% · cota 5h 34% 7d 12% · gasto ↑2.4M ↓33k · cache 97% · sub 120k · +230/-14 · api 1m12s]
```

| Key | Label | Meaning | Source |
| --- | --- | --- | --- |
| `ctx` | `token` | context window used / size, colored by pressure | payload |
| `quota` | `cota` | account rate limits, 5h and 7d windows | payload |
| `tok` | `gasto` | cumulative billed input / output tokens for the session | transcript |
| `cache` | `cache` | share of billed input served from cache — higher is better | transcript |
| `sub` | `sub` | tokens spent by subagents (sidechain entries) | transcript |
| `lines` | `+ -` | lines added / removed | payload |
| `api` | `api` | time spent waiting on the API | payload |
| `cost` | `$` | session cost — **off by default**, see below | payload |

Keys are the stable identifiers used in `CC_TOKENS_SEGMENTS`; labels are only
what gets printed. `limits` is accepted as an alias for `quota`.

`cota` is the account rate limit, not a per-session budget: both windows are
account-wide, shared across every session and machine, and neither resets when
you start a new session. Each window is colored on its own clock. Once either
crosses 70%, the reset time for the tight one is appended — the only actionable
fact at that point:

```
[token 780k/1M 78% · cota 5h 41% 7d 82% ~2h11m · gasto ↑2.4M ↓33k · cache 71%]
```

The segment disappears entirely when the payload carries no `rate_limits`
(API-key accounts do not have them).

`cost` is off by default. It reports 0 on subscription plans in some setups, and
the columns it takes are better spent on both quota windows — the quota is what
actually limits the day. Turn it on with `CC_TOKENS_SEGMENTS`.

## Install

As a plugin:

```
/plugin marketplace add Alfafis/cc-token-statusline
/plugin install cc-token-statusline@cc-token-statusline
```

Installing the plugin is not enough on its own. Claude Code reads `statusLine`
only from `settings.json`, and no plugin can register one — so the first session
after install offers to run the wiring for you. Say yes once and it is done.

Standalone, or to do the wiring yourself:

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
| `CC_TOKENS_SEGMENTS` | `ctx,quota,tok,cache,sub,lines,api` | which segments, in order. Add `cost` for the dollar figure. |
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

## Development

```
.claude-plugin/     plugin and marketplace manifests
scripts/            the badge: a bash entry point and the python that renders it
hooks/              SessionStart hook that offers the one-time wiring
commands/           /token-report
tests/              ./tests/run.sh — no dependencies beyond python3
```

`./tests/run.sh` covers the parts that are easy to get quietly wrong:
deduplication, incremental parsing against a one-shot parse, resuming from a
half-written line, quota window selection, width trimming, and every failure
mode printing nothing with exit 0. It runs against a throwaway
`CLAUDE_CONFIG_DIR`, so the real cache is untouched.

## Limitations

* `total_cost_usd` is 0 on subscription plans in some setups. The `cost` segment
  is off by default for that reason, and hides itself rather than showing a
  permanent `$0.00` when enabled.
* The cache directory grows one small file per session and is never pruned.
* The status line runs a copy under `~/.claude/hooks`, not the plugin's own
  files — a plugin path carries a version hash and would break on every update.
  So `plugin update` does not reach the badge; the SessionStart hook notices the
  drift and offers to re-run `install.sh`.
* Terminal width is read from `COLUMNS`, or from `/dev/tty` when the wrapper can
  reach it, and falls back to 80 columns otherwise — a wide terminal may drop
  segments it had room for. Set `CC_TOKENS_WIDTH` to pin it.
