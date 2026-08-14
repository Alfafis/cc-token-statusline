---
description: Full token breakdown for the current session (input, cache write/read, output, thinking, subagents)
---

Print the detailed token breakdown for the session in progress.

1. Find the transcript for this session. Transcripts live under
   `<claude-config>/projects/<slugified-cwd>/<session-id>.jsonl`, where the config
   directory is `$CLAUDE_CONFIG_DIR` if set and `~/.claude` otherwise, and the
   slug is the absolute cwd with every path separator replaced by `-` (on Windows
   the drive colon goes too: `C:\Users\me\app` becomes `C--Users-me-app`). The
   most recently modified `.jsonl` in that directory is the current session.

2. Run the report with an absolute path to the badge, not `~`, which only a
   POSIX shell expands:

   ```bash
   python3 <claude-config>/hooks/tokens_statusline.py --report <transcript.jsonl>
   ```

   On Windows the interpreter is `python` (`python3` is usually a Microsoft
   Store stub that installs nothing and runs nothing). If neither name is on
   PATH, read the interpreter out of the `statusLine` command in
   `<claude-config>/settings.json` — the installer wrote an absolute path there.

3. Show the output as-is, then add one short line of interpretation — the cache
   hit rate and the subagent share are the two numbers worth commenting on.
   A hit rate below ~70% in a long session usually means something large and
   unstable is sitting near the top of the prompt.

Do not edit any files for this command.
