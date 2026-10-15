#!/usr/bin/env bash
# 本地 Smoke：验证 A2A Agent Card；可选 --live 走一轮 ADK（需双 MCP）
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

# shellcheck disable=SC1091
source "$ROOT/scripts/lib/load_env.sh"

source "$ROOT/.venvAgents/bin/activate"
export PYTHONPATH="${ROOT}${PYTHONPATH:+:$PYTHONPATH}"

MODE="${1:-card}"
python "$ROOT/scripts/smoke_a2a_smart_agents.py" --mode="$MODE"
