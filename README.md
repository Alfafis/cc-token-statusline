# cc-token-statusline

[![tests](https://github.com/Alfafis/cc-token-statusline/actions/workflows/ci.yml/badge.svg)](https://github.com/Alfafis/cc-token-statusline/actions/workflows/ci.yml)

Status line badge for Claude Code showing what a session is actually costing.

![The badge, rendered twice: an everyday session, and one where the context is filling up and the weekly quota is getting tight](docs/badge.svg)

Colors move on their own thresholds, so the line changes shape when something
needs attention instead of reading the same at 9% and at 82%.

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
you start a new session. Each window is colored on its own clock, and they are
split by `│` rather than the `·` used between segments — same segment, two
readings. Once either
crosses 70%, the reset time for the tight one is appended — the only actionable
fact at that point:

```
[token 780k/1M 78% · cota 5h 41% │ 7d 82% ~2h11m · gasto ↑2.4M ↓33k · cache 71%]
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
python3 scripts/install.py       # python scripts/install.py on Windows
```

It copies the badge into `~/.claude/hooks` and points `statusLine` at it,
backing up every file it edits.

The wired command names the interpreter by absolute path:

```json
"statusLine": { "command": "\"/usr/bin/python3\" \"/home/me/.claude/hooks/tokens_statusline.py\"" }
```

No shell, no `bash`, no guessing whether this machine calls it `python` or
`python3` — which matters, because a stock Windows install has neither `bash`
nor a `python3.exe`, and a `statusLine` command that fails hides the entire
status bar rather than just this badge.

### Already using another status line

Claude Code allows exactly one `statusLine` command, so an existing one is
wrapped rather than replaced: it runs first, with the same payload on stdin, and
the badge is appended to whatever it prints.

```
ccusage output here  [token 93k/1M 9% · cota 5h 34% │ 7d 12% · cache 99%]
```

The wrapped command gets a 2 second timeout (`CC_TOKENS_CHAIN_TIMEOUT`) and its
failures are swallowed, so a slow or broken third-party status line cannot take
the badge — or the whole status bar — down with it.

| Flag | Effect |
| --- | --- |
| `--replace` | discard the existing statusLine instead of wrapping it |
| `--uninstall` | put the previous statusLine back, or remove ours if there was none |
| `--dry-run` | print what would change |

## Configuration

All via environment variables (settable in the `env` block of `settings.json`):

| Variable | Default | Effect |
| --- | --- | --- |
| `CC_TOKENS_SEGMENTS` | `ctx,quota,tok,cache,sub,lines,api` | which segments, in order. Add `cost` for the dollar figure. |
| `CC_TOKENS_WIDTH` | terminal width − reserve | hard cap on badge width |
| `CC_TOKENS_RESERVE` | `34` | columns left for other badges |
| `CC_TOKENS_COLOR` | `1` | `0` disables color (`NO_COLOR` works too) |
| `CC_TOKENS_ASCII` | unset | `1` forces ASCII glyphs (`|`, `^`, `v`) instead of `│ ↑ ↓` |
| `CC_TOKENS_PYTHON` | autodetected | explicit python path, honored only by the legacy bash entry point |
| `CC_TOKENS_CHAIN_TIMEOUT` | `2` | seconds allowed to a wrapped status line command |
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
scripts/            the badge, the installer and the SessionStart check
hooks/              hooks.json only
commands/           /token-report
tests/              python3 tests/run.py — no dependencies beyond the stdlib
```

`python3 tests/run.py` covers the parts that are easy to get quietly wrong:
deduplication, incremental parsing against a one-shot parse, resuming from a
half-written line, quota window selection, width trimming, and every failure
mode printing nothing with exit 0. It runs against a throwaway
`CLAUDE_CONFIG_DIR`, so the real cache is untouched.

CI runs it on Linux, macOS and Windows. Windows is in the matrix because every
portability bug this project has had was a shell assumption that no Unix runner
could catch.

## Limitations

* `total_cost_usd` is 0 on subscription plans in some setups. The `cost` segment
  is off by default for that reason, and hides itself rather than showing a
  permanent `$0.00` when enabled.
* The cache directory grows one small file per session and is never pruned.
* The status line runs a copy under `~/.claude/hooks`, not the plugin's own
  files — a plugin path carries a version hash and would break on every update.
  So `plugin update` does not reach the badge; the SessionStart hook notices the
  drift and offers to re-run the installer.
* Terminal width is read from `COLUMNS` and falls back to 80 columns — stdout is
  a pipe, so a wide terminal may drop segments it had room for. Set
  `CC_TOKENS_WIDTH` to pin it.
* Consoles that cannot encode the box-drawing and arrow glyphs (Windows `cp1252`)
  get the ASCII set automatically. Output is written as UTF-8 regardless.
