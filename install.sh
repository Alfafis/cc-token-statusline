#!/usr/bin/env bash
# Convenience wrapper. The installer itself is python, so it works the same on
# Windows, where this file cannot run at all:
#
#   python scripts/install.py
#
# Any arguments are passed straight through (--replace, --uninstall, --dry-run).

set -euo pipefail

SELF_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

for candidate in python3 python; do
  if command -v "$candidate" >/dev/null 2>&1; then
    exec "$candidate" "$SELF_DIR/scripts/install.py" "$@"
  fi
done

echo "python3 not found — the badge needs it." >&2
exit 1
