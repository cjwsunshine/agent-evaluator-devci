#!/usr/bin/env python3
"""Standalone promptfoo exec provider — calls an agent script directly.

promptfoo invokes this script for every test prompt. The prompt is passed
either as ``argv[1]`` or on stdin (promptfoo uses the latter by default).

The agent script path is read from ``$AGENT_SCRIPT`` (default:
``example_agent.py`` in the project root). This provider does NOT require
Flask, the database, or the platform's AgentService.

Agent contract: ``run(query, input_payload=None) -> str | dict`` where a
dict may contain an ``answer`` key; any other return value is str()-coerced.
"""
from __future__ import annotations

import os
import sys

# Ensure project root is on sys.path so scripts.eval_common is importable
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from scripts.eval_common import call_agent, load_agent_runner  # noqa: E402


def main() -> int:
    prompt = sys.argv[1] if len(sys.argv) > 1 else sys.stdin.read()
    if not prompt:
        # promptfoo sometimes probes providers with empty input — respond
        # gracefully instead of crashing.
        print("")
        return 0

    try:
        runner = load_agent_runner()
    except Exception as exc:  # noqa: BLE001
        print(f"[provider error] cannot load agent: {exc}", file=sys.stderr)
        print(f"Agent加载失败: {exc}")
        return 0

    answer, _payload, _latency_ms = call_agent(runner, prompt, None)
    print(answer)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
