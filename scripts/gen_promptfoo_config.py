#!/usr/bin/env python3
"""Generate ``promptfooconfig.yaml`` from ``eval_data/test_cases.json``.

Each test case's ``metrics.promptfoo_assert`` is rendered as a promptfoo
assertion. Two assertion kinds are supported:

* ``{"type": "contains", "value": "..."}`` — a built-in contains assertion
  (zero LLM cost, used for smoke-style checks).
* ``{"type": "llm-rubric", "value": "..."}`` — rendered as a Python assertion
  that calls scripts/promptfoo_grader.py against Ark. The rubric is passed
  via ``vars.__rubric``.

The generated provider is an ``exec`` provider that invokes
``scripts/promptfoo_exec_provider.py``, which in turn loads the agent
configured by ``$AGENT_SCRIPT``.

Usage:
    python scripts/gen_promptfoo_config.py [output_path]

If ``output_path`` is omitted the file is written to ``promptfooconfig.yaml``
in the project root.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import yaml

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from scripts.eval_common import (  # noqa: E402
    filter_cases_for_tool,
    load_selection,
    load_test_cases,
    tool_enabled,
)


def build_config(cases, provider_cmd: str):
    tests = []
    for case in cases:
        assertion = case.get("metrics", {}).get("promptfoo_assert") or {
            "type": "contains",
            "value": case.get("expected", ""),
        }

        vars_block = {"query": case["query"]}
        asserts = []

        atype = assertion.get("type", "contains")
        if atype == "llm-rubric":
            rubric = assertion.get("value", case.get("expected", ""))
            vars_block["__rubric"] = rubric
            asserts.append(
                {
                    "type": "python",
                    "value": "file://scripts/promptfoo_grader.py",
                }
            )
        else:
            asserts.append(
                {
                    "type": atype,
                    "value": assertion.get("value", ""),
                }
            )

        tests.append(
            {
                "description": case.get("name", case["id"]),
                "vars": vars_block,
                "assert": asserts,
            }
        )

    return {
        "prompts": ["{{query}}"],
        "providers": [
            {
                "id": f"exec:{provider_cmd}",
                "label": "agent",
                "config": {"timeout": 120000},
            }
        ],
        "tests": tests,
        "sharing": False,
        "telemetry": False,
    }


def main() -> int:
    output_path = Path(sys.argv[1]) if len(sys.argv) > 1 else BASE_DIR / "promptfooconfig.yaml"

    all_cases = load_test_cases()
    selection = load_selection()
    if not tool_enabled(selection, "promptfoo"):
        # Write a config with no tests so the CLI step is a no-op; the
        # converter marks every case skipped.
        cases: list = []
        print("[gen_promptfoo_config] promptfoo disabled in selection.json — writing empty config")
    else:
        cases, skipped = filter_cases_for_tool(all_cases, selection, "promptfoo")
        if skipped:
            print(
                f"[gen_promptfoo_config] {len(skipped)} case(s) deselected by metric filter"
            )

    python_exe = sys.executable or "python"
    provider_cmd = f"{python_exe} scripts/promptfoo_exec_provider.py"

    config = build_config(cases, provider_cmd)

    with open(output_path, "w", encoding="utf-8") as f:
        yaml.safe_dump(config, f, allow_unicode=True, sort_keys=False, width=120)

    print(f"[gen_promptfoo_config] wrote {len(cases)} cases -> {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
