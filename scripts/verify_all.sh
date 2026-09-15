#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
export AGENTFORGE_LLM_MOCK=1
python -m pip install -e ".[dev]" -q
python -m pytest -q
agentforge doctor --full
echo "verify_all OK"
