# Changelog

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
