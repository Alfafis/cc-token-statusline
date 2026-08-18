# Changelog

## Unreleased

- **Fixed: a wrapped status line could be killed for PowerShell's startup.** The
  2 second budget was meant for the wrapped command, but the timeout covers the
  interpreter starting up as well — free under bash, close to a second under
  PowerShell even with `-NoProfile`. A third-party badge that answered in time
  was cut off anyway and vanished from the bar, which is the outcome wrapping
  exists to prevent. PowerShell now gets an allowance on top of the budget
  instead of spending the budget on itself; `CC_TOKENS_CHAIN_TIMEOUT` still names
  the whole budget when it is set.

## 0.4.3

The quota segment now says which clock each countdown belongs to, and the default
bar carries only the numbers that answer whether you can keep going.

- **Fixed: the quota countdown could belong to a window you were not reading.**
  Only one reset was shown, for whichever window was further along. With the 5h
  window at 40% and the 7d at 92% the badge printed a countdown measured in days
  and nothing said which clock it came from — it read as the 5h. Each window now
  carries its own countdown.
- **The 5h countdown is always on.** It was gated at 70% along with everything
  else, so the window that stops the session in progress stayed silent until the
  quota was nearly gone. The 7d one keeps the gate: a reset days out is not worth
  the columns until that window is the real ceiling.
- **New: `--report` ends with both quota windows and the time left on each.**
  `rate_limits` only ever arrives on the status line's stdin, so the badge now
  records what it last saw in `~/.claude/statusline-cache/quota.json` and the
  report reads it from there — recording it even when `CC_TOKENS_SEGMENTS` leaves
  the quota off the bar. Percentages are a snapshot and the report dates them
  when they have aged; the countdowns are recomputed from the absolute
  `resets_at` and are always current.
- **`api` and `sub` are off by default.** Both are still implemented and both come
  back by name through `CC_TOKENS_SEGMENTS`, alongside `cost`. The reason is the
  same for all three: the badge exists to say whether you can keep going, and
  time already spent waiting, a running total for finished subagent work and a
  dollar figure that reads 0 on subscription plans do not answer that. The
  default is now `ctx,quota,tok,cache,lines`.
- **Fixed: the privacy page did not mention `quota.json`.** It has been written
  since the previous entry and the page still described the cache as one file per
  session. It also claimed nothing was ever pruned, which stopped being true in
  0.4.1 when session files gained a 30-day sweep.

## 0.4.2

Two ways a status line could be lost on Windows, and one way the badge could
print itself twice on any of them.

- **Fixed: the installer wrapped a status line that already ran the badge.** A
  combiner written by hand — one script running several badges in a row — names
  itself in `settings.json` and nothing of ours, so it was classified as
  third-party and wrapped, printing the badge twice. The installer now reads what
  a command runs before deciding, leaves such a wiring alone and only refreshes
  the copy. The SessionStart hook answers the same question the same way, so it
  no longer nudges toward an installer that would report nothing to do.
- **Fixed: a wrapped status line ran in the wrong shell on Windows.** Claude Code
  runs status line commands through Git Bash when it is installed and PowerShell
  when it is not, so the command recorded from `settings.json` is written for one
  of those. The wrapper ran it through `cmd.exe`, which expands neither `~` nor
  `$(...)` and does not know `2>/dev/null` — the third-party badge failed without
  a message and simply disappeared from the bar, which is the outcome wrapping
  exists to prevent. The shell is now chosen the way Claude Code chooses it, and
  `CC_TOKENS_CHAIN_SHELL` overrides it.
- **Fixed: the wired command could not be parsed by PowerShell.** It was written
  as `"python" "badge.py"`, which bash runs and PowerShell reads as a string
  expression before erroring on the rest — so on a Windows box without Git Bash,
  where Claude Code falls back to PowerShell, the badge hid the entire status bar
  instead of drawing it. The command is now written unquoted when no path needs
  quoting (valid in both shells) and with PowerShell's call operator when one
  does and Git Bash is absent. The SessionStart hook flags the wiring when
  installing or removing Git later flips the shell under it.

## 0.4.1

A pass over every OS-specific assumption left in the runtime and the installer.

- **Fixed: re-running the installer deleted a wrapped status line.** The second
  run saw its own wrapper in `settings.json`, decided the badge was already
  installed and pointed `statusLine` straight at it — silently dropping whatever
  third-party command it had been running first. Refreshing the copy after a
  plugin update is exactly what the SessionStart hook asks people to do, so an
  upgrade could take someone's ccusage or powerline badge with it.
- **Fixed: the badge assumed an 80 column terminal everywhere.** Width was
  measured on stdout, which Claude Code always captures, so the measurement
  always failed into the fallback and segments were dropped on terminals with
  plenty of room. Width now comes from stderr, stdout, stdin, or the console
  device (`/dev/tty`, `CONOUT$`), with `COLUMNS` and 80 as the last resorts.
- **Fixed: the wired interpreter path could stop existing.** Homebrew and pyenv
  put the patch version in the path `sys.executable` reports, so a routine python
  upgrade left `statusLine` pointing at a deleted binary — and a command that
  cannot start hides the whole status bar. The installer now prefers a launcher
  on `PATH`, and the SessionStart hook flags an absolute interpreter that has
  gone missing.
- **Fixed: the chain wrapper could still crash on a Windows console.** Our own
  glyphs already degrade to ASCII, but the wrapped command's output passed
  through untouched, so a box-drawing character in someone else's badge raised
  `UnicodeEncodeError` outside the guard.
- `--replace` over a wrapped install now forgets what it unwrapped, so a later
  refresh cannot resurrect it.
- `/token-report` no longer assumes `python3`, `~` expansion, or POSIX path
  slugs; the SessionStart hook tries the `py` launcher before bare `python`,
  which on Windows is often a Microsoft Store stub.
- Cache files untouched for 30 days are pruned when a new session appears.
- Tests: the wired command is now executed through the platform shell from a
  path containing spaces, which is how `cmd.exe` quoting bugs actually show up.

## 0.4.0

- **Labels are English by default**, switchable with `CC_TOKENS_LANG=pt` for the
  previous `token` / `cota` / `gasto`. Regional tags like `pt-BR` resolve to the
  base language and anything unknown falls back to English.
- Segment keys (`ctx`, `quota`, `tok`, ...) are unchanged and never translated —
  they are the API `CC_TOKENS_SEGMENTS` speaks, so switching language cannot
  break an existing config.

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
- **An existing status line is wrapped, not replaced.** Claude Code allows one
  `statusLine` command, and the installer used to refuse when it found someone
  else's — which made the plugin unusable next to ccusage, powerline or any
  hand-rolled script. The previous command now runs first with the same payload
  and the badge is appended to its output, under a 2 second timeout whose
  failures are swallowed. `--replace` drops it, `--uninstall` puts it back.
- The test suite is python and runs on Windows in CI. 72 tests, up from 46.

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
