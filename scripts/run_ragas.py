#!/usr/bin/env python3
"""Run RAGAS evaluation against the configured agent.

Standalone script — no Flask / DB needed (RagasEvaluator.score_output only
touches the RAGAS library + the Ark LLM client; see scripts/verify_metrics.py).

Output: ``$EVAL_OUTPUT_DIR/ragas_results.json`` in the unified schema.
Exit code: 0 if all cases scored (even if some failed), 1 on a fatal error.
"""
from __future__ import annotations

import json
import sys
import time
import types
import traceback
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from scripts.eval_common import (  # noqa: E402
    build_case_record,
    call_agent,
    ensure_on_path,
    filter_cases_for_tool,
    load_agent_runner,
    load_selection,
    load_test_cases,
    resolve_output_dir,
    write_tool_results,
)


def _safe_details(details) -> dict:
    if not isinstance(details, dict):
        return {}
    clean = {}
    for k, v in details.items():
        try:
            json.dumps(v)
            clean[k] = v
        except (TypeError, ValueError):
            clean[k] = repr(v)
    return clean


def _skip_record(case: dict, reason: str) -> dict:
    metric = case.get("metrics", {}).get("ragas", "answer_relevancy")
    if reason == "tool_disabled":
        label = "工具已关闭"
    elif reason == "not_configured":
        label = "该用例未配置 RAGAS 指标"
    else:
        label = f"指标 {metric} 未勾选"
    return build_case_record(
        case,
        metric=metric,
        agent_output="",
        score=None,
        status="skipped",
        error=label,
        latency_ms=0.0,
        details={"skip_reason": reason},
    )


def main() -> int:
    ensure_on_path()
    output_dir = resolve_output_dir()
    selection = load_selection()

    all_cases = load_test_cases()
    cases, skipped_cases = filter_cases_for_tool(all_cases, selection, "ragas")

    records = [
        _skip_record(c, c.get("_skip_reason", "metric_filtered"))
        for c in skipped_cases
    ]

    if not cases:
        print(
            f"[RAGAS] no cases selected ({len(skipped_cases)} skipped) -> "
            f"writing skip-only results",
        )
        out = write_tool_results(
            output_dir=output_dir, tool="ragas", cases=records, duration_s=0.0
        )
        print(f"[RAGAS] -> {out}")
        return 0

    try:
        from app.services.evaluation_engine import RagasEvaluator
    except ImportError as exc:
        print(f"[ERROR] cannot import RagasEvaluator: {exc}", file=sys.stderr)
        traceback.print_exc()
        return 1

    runner = load_agent_runner()
    evaluator = RagasEvaluator(types.SimpleNamespace(selected_metrics=[]))

    print(
        f"[RAGAS] evaluating {len(cases)} cases "
        f"({len(skipped_cases)} skipped) -> {output_dir}"
    )
    t_start = time.time()
    fatal = False

    for idx, case in enumerate(cases, 1):
        metric = case.get("metrics", {}).get("ragas", "answer_relevancy")
        query = case["query"]
        input_payload = case.get("input_payload")
        expected_payload = case.get("expected_payload")

        print(f"  [{idx}/{len(cases)}] {case['id']} ({metric})...", flush=True)
        answer, payload, latency_ms = call_agent(runner, query, input_payload)

        try:
            score, status, err, details = evaluator.score_output(
                agent_output=answer,
                expected=case.get("expected", ""),
                query=query,
                metric=metric,
                input_payload=input_payload,
                expected_payload=expected_payload,
                agent_output_payload=payload,
            )
        except Exception as exc:  # noqa: BLE001
            print(f"    [CRASH] {type(exc).__name__}: {exc}", file=sys.stderr)
            score, status, err, details = (
                0.0,
                "failed",
                f"RAGAS exception: {exc}",
                {"exception_type": type(exc).__name__},
            )
            fatal = True

        record = build_case_record(
            case,
            metric=metric,
            agent_output=answer,
            score=score,
            status=status,
            error=err,
            latency_ms=latency_ms,
            details=_safe_details(details),
        )
        records.append(record)
        print(
            f"    -> {status} score={record['score']} "
            f"({record['latency_ms']}ms)"
        )

    duration_s = time.time() - t_start
    out = write_tool_results(
        output_dir=output_dir,
        tool="ragas",
        cases=records,
        duration_s=duration_s,
    )
    passed = sum(1 for r in records if r["status"] == "passed")
    print(
        f"[RAGAS] total={len(records)} passed={passed} "
        f"skipped={sum(1 for r in records if r['status']=='skipped')} "
        f"duration={round(duration_s, 1)}s -> {out}"
    )

    # A crash in any case means the pipeline step should fail; individual
    # failed assertions (status=failed) are still a valid run and return 0.
    return 1 if fatal else 0


if __name__ == "__main__":
    raise SystemExit(main())
