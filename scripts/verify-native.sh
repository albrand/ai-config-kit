#!/bin/sh
# Run the checkout's native suites: they apply their own OS sandbox, which a sandboxed runner job cannot nest.
cd "$(dirname "$0")/.." || exit 1
exec python3 -I scripts/verify-unit.py --native
