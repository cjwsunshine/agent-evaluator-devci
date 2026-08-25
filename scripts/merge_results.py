#!/usr/bin/env python3
"""Merge per-tool result JSONs into a single ``summary.json``.

Reads:
    $EVAL_OUTPUT_DIR/deepeval_results.json
    $EVAL_OUTPUT_DIR/promptfoo_results.json
    $EVAL_OUTPUT_DIR/trulens_results.json

Writes:
    $EVAL_OUTPUT_DIR/summary.json
    ./eval_output/history.jsonl  (one JSON line per run; append-only)

Missing tool files are tolerated — that tool is reported as ``not_run`` so
the report can still render (for example when promptfoo was skipped due to
a missing Node setup).
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from scripts.eval_common import agent_label, load_test_cases, resolve_output_dir  # noqa: E402

TOOLS = ("deepeval", "promptfoo", "trulens", "ragas")


def _load_tool(output_dir: Path, tool: str) -> dict[str, Any] | None:
    path = output_dir / f"{tool}_results.json"
    if not path.exists():
        print(f"[merge] WARN: {path} not found — marking {tool} as not_run")
        return None
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _tool_summary(data: dict | None) -> dict[str, Any]:
    if data is None:
        return {
            "status": "not_run",
            "avg_score": None,
            "pass_rate": None,
            "passed": 0,
            "failed": 0,
            "skipped": 0,
            "total": 0,
            "duration_s": None,
        }
    passed = int(data.get("passed", 0))
    failed = int(data.get("failed", 0))
    skipped = int(data.get("skipped", 0))
    # Denominator is only the cases actually scored; skipped cases don't count.
    scored = passed + failed
    pass_rate = round(passed / scored, 4) if scored else None
    status = "ok"
    if scored == 0 and skipped > 0:
        status = "skipped"
    return {
        "status": status,
        "avg_score": data.get("avg_score"),
        "pass_rate": pass_rate,
        "passed": passed,
        "failed": failed,
        "skipped": skipped,
        "total": scored,
        "duration_s": data.get("duration_s"),
    }


def _extract_breakdown(tool: str, details: dict) -> dict:
    """Pull the human-meaningful scoring detail out of a tool's per-case dict.

    Keeps the summary.json small: only the fields the HTML report renders.
    """
    b: dict[str, Any] = {}
    judge = details.get("judge_model")
    if judge:
        b["judge_model"] = judge
    if tool == "deepeval":
        for k_in, k_out in (
            ("deepeval_raw_score", "raw_score"),
            ("deepeval_threshold", "threshold"),
            ("deepeval_metric_class", "metric_class"),
        ):
            if details.get(k_in) is not None:
                b[k_out] = details[k_in]
        if details.get("deepeval_reason"):
            b["reason"] = details["deepeval_reason"]
    elif tool == "trulens":
        for k_in, k_out in (
            ("trulens_raw_score", "raw_score"),
            ("trulens_used_metric", "metric_impl"),
        ):
            if details.get(k_in) is not None:
                b[k_out] = details[k_in]
        if details.get("trulens_reason"):
            b["reason"] = details["trulens_reason"]
    elif tool == "promptfoo":
        gr = details.get("gradingResult") or {}
        if isinstance(gr, dict):
            if gr.get("reason"):
                b["reason"] = gr["reason"]
            if gr.get("pass") is not None:
                b["assert_pass"] = gr["pass"]
        if details.get("failureReason"):
            b["failure_reason"] = details["failureReason"]
        tok = details.get("tokenUsage") or {}
        if isinstance(tok, dict) and tok.get("total"):
            b["tokens"] = tok["total"]
    return b


def _build_case_breakdown(
    test_cases: list[dict], tool_data: dict[str, dict | None]
) -> list[dict[str, Any]]:
    """Build per-case records keyed by case id, attaching each tool's result."""
    # Index each tool's cases by id for lookup.
    by_tool: dict[str, dict[str, dict]] = {}
    for tool, data in tool_data.items():
        if not data:
            by_tool[tool] = {}
            continue
        by_tool[tool] = {c["id"]: c for c in data.get("cases", []) if c.get("id")}

    rows = []
    for meta in test_cases:
        cid = meta["id"]
        row = {
            "id": cid,
            "name": meta.get("name", cid),
            "query": meta.get("query", ""),
            "expected": meta.get("expected", ""),
        }
        for tool in TOOLS:
            case_result = by_tool.get(tool, {}).get(cid)
            if case_result is None:
                row[tool] = {
                    "score": None,
                    "status": "not_run",
                    "error": None,
                    "metric": meta.get("metrics", {}).get(tool),
                }
            else:
                row[tool] = {
                    "score": case_result.get("score"),
                    "status": case_result.get("status"),
                    "error": case_result.get("error"),
                    "metric": case_result.get("metric"),
                    "agent_output": case_result.get("agent_output", ""),
                    "latency_ms": case_result.get("latency_ms"),
                    "breakdown": _extract_breakdown(tool, case_result.get("details") or {}),
                }
        rows.append(row)
    return rows


def _overall(tools_summary: dict[str, dict], case_rows: list[dict]) -> dict:
    tools_run = sum(1 for t in tools_summary.values() if t["status"] == "ok")
    total_passed = sum(t["passed"] for t in tools_summary.values())
    total_failed = sum(t["failed"] for t in tools_summary.values())
    total_skipped = sum(t["skipped"] for t in tools_summary.values())
    total_scored = total_passed + total_failed
    pass_rate = round(total_passed / total_scored, 4) if total_scored else None

    scored_avgs = [
        t["avg_score"]
        for t in tools_summary.values()
        if t["status"] == "ok" and t["avg_score"] is not None
    ]
    avg_score = round(sum(scored_avgs) / len(scored_avgs), 2) if scored_avgs else None

    return {
        "total_cases": len(case_rows),
        "tools_run": tools_run,
        "avg_score": avg_score,
        "pass_rate": pass_rate,
        "total_passed": total_passed,
        "total_failed": total_failed,
        "total_skipped": total_skipped,
    }


def _append_history(history_path: Path, summary: dict) -> None:
    history_path.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "run_id": summary["run_id"],
        "timestamp": summary["timestamp"],
        "agent_script": summary.get("agent_script"),
        "avg_score": summary["overall"]["avg_score"],
        "pass_rate": summary["overall"]["pass_rate"],
        "tools_run": summary["overall"]["tools_run"],
        "total_passed": summary["overall"]["total_passed"],
        "total_failed": summary["overall"]["total_failed"],
    }
    with open(history_path, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def main() -> int:
    output_dir = resolve_output_dir()
    test_cases = load_test_cases()

    tool_data = {tool: _load_tool(output_dir, tool) for tool in TOOLS}
    tools_summary = {tool: _tool_summary(data) for tool, data in tool_data.items()}
    case_rows = _build_case_breakdown(test_cases, tool_data)
    overall = _overall(tools_summary, case_rows)

    run_id = output_dir.name
    timestamp = datetime.now().isoformat(timespec="seconds")
    agent_script = agent_label()

    summary = {
        "run_id": run_id,
        "timestamp": timestamp,
        "agent_script": agent_script,
        "overall": overall,
        "tools": tools_summary,
        "cases": case_rows,
    }

    summary_path = output_dir / "summary.json"
    with open(summary_path, "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)

    history_path = BASE_DIR / "eval_output" / "history.jsonl"
    _append_history(history_path, summary)

    ran = sum(1 for t in tools_summary.values() if t["status"] != "not_run")
    print(f"[merge] wrote {summary_path}")
    print(
        f"[merge] overall: avg_score={overall['avg_score']} "
        f"pass_rate={overall['pass_rate']} "
        f"passed={overall['total_passed']} failed={overall['total_failed']} "
        f"tools_run={overall['tools_run']}/{ran}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
