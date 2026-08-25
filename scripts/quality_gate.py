#!/usr/bin/env python3
"""Quality gate: fail the pipeline if summary metrics are below thresholds.

Reads ``$EVAL_OUTPUT_DIR/summary.json`` and compares the overall stats against
thresholds passed via environment variables:

    GATE_MIN_AVG_SCORE   (default 60,   range 0-100)
    GATE_MIN_PASS_RATE   (default 0.7,  range 0-1)

Tools that did not run are not penalized, but if zero tools produced results
the gate fails. Exit code 0 on pass, 1 on fail.

In pipeline.hcl this step is wrapped with ``|| true`` so that a gate failure
shows up as a warning in the log but does not abort the build before the
report is visible.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from scripts.eval_common import resolve_output_dir  # noqa: E402


def _as_float(value, default):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def main() -> int:
    output_dir = resolve_output_dir()
    summary_path = output_dir / "summary.json"
    if not summary_path.exists():
        print(f"[gate] ERROR: summary not found: {summary_path}", file=sys.stderr)
        return 1

    with open(summary_path, "r", encoding="utf-8") as f:
        summary = json.load(f)

    overall = summary.get("overall", {})
    avg = overall.get("avg_score")
    pass_rate = overall.get("pass_rate")
    tools_run = overall.get("tools_run", 0)

    min_avg = _as_float(os.environ.get("GATE_MIN_AVG_SCORE"), 60.0)
    min_pass = _as_float(os.environ.get("GATE_MIN_PASS_RATE"), 0.7)

    print(
        f"[gate] avg_score={avg} (min {min_avg}), "
        f"pass_rate={pass_rate} (min {min_pass}), tools_run={tools_run}/3"
    )

    failures = []

    if tools_run == 0:
        failures.append("没有任何评测工具产出结果")

    if avg is None:
        failures.append("综合平均分为空")
    elif avg < min_avg:
        failures.append(
            f"综合平均分 {avg:.2f} 低于阈值 {min_avg:.2f}"
        )

    if pass_rate is None:
        failures.append("通过率为空")
    elif pass_rate < min_pass:
        failures.append(
            f"通过率 {pass_rate * 100:.1f}% 低于阈值 {min_pass * 100:.1f}%"
        )

    if failures:
        print("[gate] ❌ 门禁未通过:", file=sys.stderr)
        for f in failures:
            print(f"  - {f}", file=sys.stderr)
        return 1

    print("[gate] ✅ 门禁通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
