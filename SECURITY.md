# Security

## Reporting a vulnerability

Open a [private security advisory](https://github.com/Alfafis/cc-token-statusline/security/advisories/new).
Please do not open a public issue for a vulnerability. If GitHub advisories are
not available to you, mail betech@developercorp.com.

Expect a first reply within 7 days.

## What this plugin can reach

The badge is a python3 script run by the status line on every render, plus a
bash entry point and one SessionStart hook. That is the entire attack surface.

**Reads**

* the status line JSON payload on stdin (context window, cost, rate limits,
  model, transcript path — all produced by Claude Code itself);
* the session transcript at the path that payload names;
* its own cache under `$CLAUDE_CONFIG_DIR/statusline-cache/`;
* `settings.json`, `settings.local.json` and `combined-statusline.sh`, only to
  check whether the badge is already wired (the SessionStart hook greps for a
  filename and reads nothing else out of them).

**Writes**

* one cache file per session under `$CLAUDE_CONFIG_DIR/statusline-cache/`,
  containing token counters and request ids — no prompt or response content;
* nothing else at runtime. `install.sh` is the only component that edits
  `settings.json` or copies files, it runs only when invoked, and it backs up
  every file it touches.

**Does not**

* make any network request, at install time or at runtime;
* ship or start an MCP server;
* read, store or transmit credentials, API keys or message content;
* depend on any third-party package — python3 standard library only.

## Failure behavior

Every error path prints nothing and exits 0. This is deliberate: a non-zero exit
hides the whole status bar, so a bug here degrades to an empty badge rather than
to a broken terminal. The bash entry point also swallows stderr so a failure
cannot write into the status line.

Two inputs are treated as untrusted even though they come from the local
machine:

* **transcript contents** — parsed as JSON per line, with malformed lines
  skipped; only numeric fields are read out of `usage`, and nothing from the
  transcript is ever printed to the terminal, so a crafted transcript cannot
  inject ANSI escapes into your prompt;
* **`CLAUDE_PLUGIN_ROOT`** — a path containing a quote or backslash makes the
  SessionStart hook stay silent rather than emit malformed JSON into the hook
  channel.

## Supported versions

The latest release on `main`. Older versions are not patched.
