#!/usr/bin/env python3
"""Convert promptfoo's native JSON output to the unified eval schema.

Reads ``$EVAL_OUTPUT_DIR/promptfoo_raw.json`` and writes
``$EVAL_OUTPUT_DIR/promptfoo_results.json``.

The test cases JSON (``eval_data/test_cases.json``) is used to enrich each
result with its stable ``id`` and metadata. Matching is by index because
promptfoo preserves the test order.
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from scripts.eval_common import (  # noqa: E402
    build_case_record,
    filter_cases_for_tool,
    load_selection,
    load_test_cases,
    resolve_output_dir,
    tool_enabled,
    write_tool_results,
)


def _extract_items(raw: dict) -> list[dict]:
    """Promptfoo wraps results in results.results; tolerate both shapes."""
    if not isinstance(raw, dict):
        return []
    results = raw.get("results", raw)
    if isinstance(results, dict):
        items = results.get("results")
        if isinstance(items, list):
            return items
    if isinstance(results, list):
        return results
    return []


def _item_score(item: dict) -> tuple[float | None, bool, str | None, str]:
    """Return (score 0-100, passed, reason, metric_label)."""
    grading = item.get("gradingResult") or {}
    raw_score = grading.get("score")
    passed = bool(grading.get("pass", False))
    reason = grading.get("reason") or grading.get("text")

    # Look for any named assertion that succeeded/failed for a richer label.
    named_assert = ""
    for component in grading.get("componentResults") or []:
        pass_ = component.get("pass")
        assertion = component.get("assertion") or {}
        atype = assertion.get("type", "assertion")
        if pass_ is False:
            named_assert = atype
            reason = reason or component.get("reason") or f"{atype} failed"
            break
        if pass_ is True and not named_assert:
            named_assert = atype

    if raw_score is None:
        return (100.0 if passed else 0.0), passed, reason, named_assert or "assertion"
    try:
        raw_score_f = float(raw_score)
    except (TypeError, ValueError):
        return (100.0 if passed else 0.0), passed, reason, named_assert or "assertion"
    score = raw_score_f * 100 if raw_score_f <= 1 else raw_score_f
    return round(score, 2), passed, reason, named_assert or "assertion"


def _item_output(item: dict) -> str:
    response = item.get("response") or {}
    output = response.get("output")
    if output is None:
        output = response.get("raw") or item.get("raw") or ""
    if isinstance(output, (dict, list)):
        return json.dumps(output, ensure_ascii=False)
    return str(output)


def _item_latency(item: dict) -> float:
    latency_ms = item.get("latencyMs")
    if latency_ms is None:
        response = item.get("response") or {}
        latency_ms = response.get("latencyMs") or 0
    try:
        return float(latency_ms)
    except (TypeError, ValueError):
        return 0.0


def _skip_record(case: dict, reason: str) -> dict:
    assert_cfg = case.get("metrics", {}).get("promptfoo_assert") or {}
    metric = assert_cfg.get("type", "contains") if isinstance(assert_cfg, dict) else assert_cfg
    label = "工具已关闭" if reason == "tool_disabled" else f"指标 {metric} 未勾选"
    return build_case_record(
        case,
        metric=metric or "contains",
        agent_output="",
        score=None,
        status="skipped",
        error=label,
        latency_ms=0.0,
        details={"skip_reason": reason},
    )


def main() -> int:
    output_dir = resolve_output_dir()
    selection = load_selection()
    all_cases = load_test_cases()
    run_cases, skipped_cases = filter_cases_for_tool(
        all_cases, selection, "promptfoo"
    )

    records = [
        _skip_record(c, c.get("_skip_reason", "metric_filtered"))
        for c in skipped_cases
    ]

    if not run_cases or not tool_enabled(selection, "promptfoo"):
        print(
            f"[Promptfoo] no cases selected ({len(skipped_cases)} skipped) -> "
            "writing skip-only results"
        )
        out = write_tool_results(
            output_dir=output_dir, tool="promptfoo", cases=records, duration_s=0.0
        )
        print(f"[Promptfoo] -> {out}")
        return 0

    raw_path = output_dir / "promptfoo_raw.json"
    if not raw_path.exists():
        print(f"[ERROR] promptfoo raw output not found: {raw_path}", file=sys.stderr)
        return 1

    with open(raw_path, "r", encoding="utf-8") as f:
        raw = json.load(f)

    items = _extract_items(raw)
    if not items:
        print(
            "[WARN] promptfoo raw output contains no result items; "
            "writing skip-only report",
            file=sys.stderr,
        )

    t0 = time.time()
    for idx, item in enumerate(items):
        # Match against the SELECTED cases (same order gen_promptfoo_config used).
        meta = run_cases[idx] if idx < len(run_cases) else {
            "id": f"case-{idx}",
            "name": f"Case {idx}",
            "query": "",
            "expected": "",
        }
        score, passed, reason, metric_label = _item_score(item)
        agent_output = _item_output(item)
        latency_ms = _item_latency(item)

        record = build_case_record(
            meta,
            metric=metric_label,
            agent_output=agent_output,
            score=score,
            status="passed" if passed else "failed",
            error=reason if not passed else None,
            latency_ms=latency_ms,
            details={
                "promptfoo_assertion": (
                    meta.get("metrics", {}).get("promptfoo_assert")
                ),
                "gradingResult": item.get("gradingResult"),
                "tokenUsage": (item.get("response") or {}).get("tokenUsage"),
                "success": item.get("success"),
                "failureReason": item.get("failureReason"),
            },
        )
        records.append(record)

    # Re-order so all cases (selected + skipped) follow test_cases.json order,
    # which the merge step expects for stable display.
    order = {c["id"]: i for i, c in enumerate(all_cases)}
    records.sort(key=lambda r: order.get(r["id"], 999))

    duration_s = time.time() - t0
    out = write_tool_results(
        output_dir=output_dir,
        tool="promptfoo",
        cases=records,
        duration_s=duration_s,
        extra={"raw_output_path": str(raw_path)},
    )
    passed = sum(1 for r in records if r["status"] == "passed")
    print(
        f"[Promptfoo] total={len(records)} passed={passed} "
        f"skipped={sum(1 for r in records if r['status']=='skipped')} -> {out}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
