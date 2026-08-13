---
description: Full token breakdown for the current session (input, cache write/read, output, thinking, subagents)
---

Print the detailed token breakdown for the session in progress.

1. Find the transcript for this session. Transcripts live under
   `~/.claude/projects/<slugified-cwd>/<session-id>.jsonl`, where the slug is the
   absolute cwd with `/` replaced by `-`. The most recently modified `.jsonl` in
   that directory is the current session.

2. Run the report:

   ```bash
   python3 ~/.claude/hooks/tokens_statusline.py --report <transcript.jsonl>
   ```

3. Show the output as-is, then add one short line of interpretation — the cache
   hit rate and the subagent share are the two numbers worth commenting on.
   A hit rate below ~70% in a long session usually means something large and
   unstable is sitting near the top of the prompt.

Do not edit any files for this command.
