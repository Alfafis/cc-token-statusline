#!/usr/bin/env bash
# Test suite for the token status line badge. No dependencies beyond python3.
#
#   ./tests/run.sh
#
# Runs against a throwaway CLAUDE_CONFIG_DIR so the real cache is untouched.

set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SCRIPT="$ROOT/scripts/tokens_statusline.py"
FIXTURE="$ROOT/tests/fixtures/transcript.jsonl"

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT
export CLAUDE_CONFIG_DIR="$WORK/claude"
mkdir -p "$CLAUDE_CONFIG_DIR"

PASS=0
FAIL=0

ok() {
  PASS=$((PASS + 1))
  printf '  ok   %s\n' "$1"
}

no() {
  FAIL=$((FAIL + 1))
  printf '  FAIL %s\n' "$1"
  printf '       expected: %s\n' "$2"
  printf '       actual:   %s\n' "$3"
}

check() {
  # check <name> <expected> <actual>
  if [ "$2" = "$3" ]; then ok "$1"; else no "$1" "$2" "$3"; fi
}

contains() {
  # contains <name> <needle> <haystack>
  case "$3" in
    *"$2"*) ok "$1" ;;
    *) no "$1" "contains '$2'" "$3" ;;
  esac
}

lacks() {
  case "$3" in
    *"$2"*) no "$1" "must not contain '$2'" "$3" ;;
    *) ok "$1" ;;
  esac
}

# payload <transcript> <ctx_used> <ctx_pct> <pct5> <pct7> [session]
payload() {
  python3 - "$@" <<'PY'
import json, sys, datetime
transcript, used, pct, pct5, pct7 = sys.argv[1:6]
session = sys.argv[6] if len(sys.argv) > 6 else "test"
reset = (
    datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=2, minutes=12)
).isoformat().replace("+00:00", "Z")
out = {
    "session_id": session,
    "transcript_path": transcript,
    "cost": {
        "total_cost_usd": 1.23,
        "total_api_duration_ms": 72000,
        "total_lines_added": 230,
        "total_lines_removed": 14,
    },
    "context_window": {
        "total_input_tokens": int(used),
        "context_window_size": 1000000,
        "used_percentage": float(pct),
    },
}
if float(pct5) >= 0:
    out["rate_limits"] = {
        "five_hour": {"used_percentage": float(pct5), "resets_at": reset},
        "seven_day": {"used_percentage": float(pct7), "resets_at": reset},
    }
print(json.dumps(out))
PY
}

badge() {
  # badge <payload-json> [extra env assignments...]
  local input="$1"
  shift
  printf '%s' "$input" | env NO_COLOR=1 CC_TOKENS_WIDTH=400 "$@" python3 "$SCRIPT"
}

totals() {
  # totals <session-id> <field>
  python3 - "$CLAUDE_CONFIG_DIR/statusline-cache/tokens-$1.json" "$2" <<'PY'
import json, sys
print(json.load(open(sys.argv[1]))["totals"][sys.argv[2]])
PY
}

echo "transcript parsing"

# Three copies of req_A, two of req_B, two of a sidechain req_S. Counting every
# line instead of every request would inflate these by ~2.5x.
out=$(badge "$(payload "$FIXTURE" 93000 9.3 34 12 dedup)")
check "dedup: main requests"        "2"    "$(totals dedup requests)"
check "dedup: input"                "15"   "$(totals dedup input)"
check "dedup: cache creation"       "300"  "$(totals dedup cache_creation)"
check "dedup: cache read"           "3000" "$(totals dedup cache_read)"
check "dedup: output"               "80"   "$(totals dedup output)"
check "dedup: thinking"             "20"   "$(totals dedup thinking)"
check "dedup: sidechain requests"   "1"    "$(totals dedup sub_requests)"
check "dedup: sidechain output"     "25"   "$(totals dedup sub_output)"

# Resuming from a cached byte offset must land on the same totals as one pass.
split="$WORK/split.jsonl"
head -n 4 "$FIXTURE" > "$split"
badge "$(payload "$split" 93000 9.3 34 12 incr)" > /dev/null
cp "$FIXTURE" "$split"
badge "$(payload "$split" 93000 9.3 34 12 incr)" > /dev/null
badge "$(payload "$FIXTURE" 93000 9.3 34 12 once)" > /dev/null
check "incremental == one-shot: cache read" "$(totals once cache_read)" "$(totals incr cache_read)"
check "incremental == one-shot: output"     "$(totals once output)"     "$(totals incr output)"
check "incremental == one-shot: requests"   "$(totals once requests)"   "$(totals incr requests)"

# Claude Code appends while the status line renders, so a half-written last line
# must be left for the next run instead of being dropped or double counted.
torn="$WORK/torn.jsonl"
python3 - "$FIXTURE" "$torn" <<'PY'
import sys
data = open(sys.argv[1], "rb").read()
open(sys.argv[2], "wb").write(data[: len(data) // 2])
PY
badge "$(payload "$torn" 93000 9.3 34 12 torn)" > /dev/null
cp "$FIXTURE" "$torn"
badge "$(payload "$torn" 93000 9.3 34 12 torn)" > /dev/null
check "torn line resumes cleanly" "$(totals once cache_read)" "$(totals torn cache_read)"
check "torn line no double count" "$(totals once requests)"   "$(totals torn requests)"

echo "rendering"

out=$(badge "$(payload "$FIXTURE" 93000 9.3 34 12 r1)")
contains "wrapped in one bracket"   "[token 93k/1M 9% ·" "$out"
contains "ends with bracket"        "api 1m12s]"         "$out"
contains "quota shows tighter window" "cota 5h 34%"      "$out"
lacks    "quota hides slack window"   "7d"               "$out"
lacks    "no reset while quota is low" "~"               "$out"

out=$(badge "$(payload "$FIXTURE" 780000 78 41 82 r2)")
contains "quota switches to worse window" "cota 7d 82%" "$out"
contains "reset appended past 70%"        "~2h1"        "$out"

out=$(badge "$(payload "$FIXTURE" 93000 9.3 -1 -1 r3)")
lacks "quota absent without rate_limits" "cota" "$out"

out=$(printf '%s' "$(payload "$FIXTURE" 93000 9.3 34 12 r4)" \
  | env NO_COLOR=1 CC_TOKENS_WIDTH=46 python3 "$SCRIPT")
contains "narrow keeps context first" "[token 93k/1M 9%" "$out"
lacks    "narrow drops api"           "api"             "$out"
if [ "${#out}" -le 46 ]; then ok "narrow respects width"; else no "narrow respects width" "<=46 chars" "${#out}"; fi

out=$(badge "$(payload "$FIXTURE" 93000 9.3 34 12 r5)" CC_TOKENS_SEGMENTS=ctx,limits)
contains "limits still aliases quota" "cota 5h 34%" "$out"

echo "failure modes"

out=$(printf '' | python3 "$SCRIPT"; printf ':%s' "$?")
check "empty stdin prints nothing" ":0" "$out"

out=$(printf 'not json' | python3 "$SCRIPT"; printf ':%s' "$?")
check "garbage stdin prints nothing" ":0" "$out"

out=$(printf '{}' | python3 "$SCRIPT"; printf ':%s' "$?")
check "empty payload prints no bare brackets" ":0" "$out"

out=$(badge '{"session_id":"missing","transcript_path":"/nope/does-not-exist.jsonl","context_window":{"total_input_tokens":100,"context_window_size":1000,"used_percentage":10},"cost":{}}')
check "missing transcript still renders context" "[token 100/1k 10%]" "$out"

echo "shell syntax"
for script in "$ROOT/scripts/tokens-statusline.sh" "$ROOT/hooks/setup-check.sh" "$ROOT/install.sh"; do
  if bash -n "$script" 2>/dev/null; then ok "syntax $(basename "$script")"; else no "syntax $(basename "$script")" "parses" "error"; fi
done

echo "json manifests"
for manifest in "$ROOT/.claude-plugin/plugin.json" "$ROOT/.claude-plugin/marketplace.json" "$ROOT/hooks/hooks.json"; do
  if python3 -c "import json,sys;json.load(open(sys.argv[1]))" "$manifest" 2>/dev/null; then
    ok "valid $(basename "$manifest")"
  else
    no "valid $(basename "$manifest")" "parses" "error"
  fi
done

printf '\n%s passed, %s failed\n' "$PASS" "$FAIL"
[ "$FAIL" -eq 0 ]
