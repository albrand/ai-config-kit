#!/bin/sh
# Run the checkout's complete self-contained test inventory.
cd "$(dirname "$0")/.." || exit 1
exec python3 -I scripts/verify-unit.py
