# Changelog

## 0.3.0

Windows support, proven by CI rather than assumed.

- **Fixed: the badge took the whole status bar down on Windows.** Consoles there
  hand python a `cp1252` stdout, which cannot encode the separators or arrows.
  The write sat outside the error guard, so the process exited non-zero — and a
  failing `statusLine` command hides the entire bar, including other plugins'
  badges. stdout is now UTF-8, glyphs fall back to ASCII twins when a console
  refuses them, and `CC_TOKENS_ASCII=1` forces the plain set.
- **No shell in the runtime path.** `install.py` wires `statusLine` to this
  interpreter by absolute path, so nothing depends on `bash` existing or on
  whether the machine calls it `python` or `python3` — a stock Windows install
  has neither `bash` nor `python3.exe`.
- `setup-check.sh` is now `setup_check.py`, so the SessionStart nudge works on
  Windows too. It also detects a badge still wired through the old bash entry
  point on a machine without bash, and offers to repair it.
- `install.py` replaces `install.sh` (kept as a passthrough wrapper), and adds
  `--replace`, `--uninstall` and `--dry-run`. Uninstall restores whatever
  statusLine was there before.
- The test suite is python and runs on Windows in CI. 63 tests, up from 46.

## 0.2.3

- Project site at https://alfafis.github.io/cc-token-statusline/, served from
  `docs/` on `main`. Both manifests now point `homepage` at it.

## 0.2.2

- A malformed `usage` entry in the transcript now costs one entry instead of the
  whole badge — that parse runs outside the per-segment error guard.
- Added `SECURITY.md` and a rendered badge image in the README.

## 0.2.1

- The two quota windows are separated by a dim `│`, distinct from the `·`
  between segments, so they read as one segment with two windows.

## 0.2.0

- `cota` now shows both rate limit windows (5h and 7d), each colored on its own
  clock, with a single reset time appended for whichever one is tight.
- `cost` moved out of the default segments. It reports 0 on subscription plans
  in some setups, and the columns pay for the second quota window instead. Still
  available through `CC_TOKENS_SEGMENTS`.

## 0.1.0

First release.

- Status line badge: context window, account quota, session cost, cumulative
  tokens, cache hit rate, subagent spend, edited lines, API time.
- Segments are dropped by priority when the badge does not fit the terminal.
- Transcript parsing deduplicated by `requestId` and resumed from a cached byte
  offset, so re-renders stay cheap on long sessions.
- `--report` for the full breakdown, also exposed as `/token-report`.
- `install.sh` wires the badge into `settings.json`, or registers it in an
  existing `combined-statusline.sh`, backing up whatever it edits.
- SessionStart hook offers the wiring once, since a plugin cannot register a
  `statusLine` by itself.
