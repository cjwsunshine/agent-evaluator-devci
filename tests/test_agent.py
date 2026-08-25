"""DeepEval evaluation cases.

Each test corresponds to one entry in eval_data/test_cases.json. The test
calls the agent, scores the output with the existing DeepEvalEvaluator
(no Flask / DB needed — see scripts/verify_metrics.py for the pattern),
and records a unified case record.

Individual case scores (status == "failed") do NOT fail the pytest step —
they are recorded into deepeval_results.json and surfaced by the report and
quality gate. Only infrastructure errors (agent crash, evaluator import
failure, etc.) fail the step, which is why exceptions re-raise as
pytest.fail.

Run:
    python -m pytest tests/ --json-report --json-report-file=/dev/null -v
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from scripts.eval_common import (  # noqa: E402
    build_case_record,
    call_agent,
    filter_cases_for_tool,
    load_selection,
    load_test_cases,
)

ALL_CASES = load_test_cases()
# Apply the tool/metric selection (eval_data/selection.json) at collection
# time so deselected cases never invoke the agent or LLM judge. conftest
# writes "skipped" records for them so the report shows the distinction.
SELECTION = load_selection()
RUN_CASES, _SKIPPED = filter_cases_for_tool(ALL_CASES, SELECTION, "deepeval")
CASE_IDS = [c["id"] for c in RUN_CASES]


@pytest.mark.parametrize("case", RUN_CASES, ids=CASE_IDS)
def test_agent_deepeval(case, evaluator, agent_runner, record_result):
    metric = case.get("metrics", {}).get("deepeval", "task_completion")
    query = case["query"]
    input_payload = case.get("input_payload")
    expected_payload = case.get("expected_payload")

    answer, payload, latency_ms = call_agent(agent_runner, query, input_payload)

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
    except Exception as exc:  # noqa: BLE001 - infrastructure error, fail the step
        record = build_case_record(
            case,
            metric=metric,
            agent_output=answer,
            score=0.0,
            status="failed",
            error=f"DeepEval exception: {exc}",
            latency_ms=latency_ms,
            details={"exception_type": type(exc).__name__},
        )
        record_result(record)
        pytest.fail(f"DeepEval raised {type(exc).__name__}: {exc}")

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
    record_result(record)

    # Note: we intentionally do NOT assert on status here. A low/failing
    # score is a valid evaluation outcome that the report and quality gate
    # are responsible for surfacing; failing the pytest step would prevent
    # merge/report from running.
    if status != "passed":
        pytest.xfail(
            f"[{case['id']}] metric={metric} score={score} "
            f"status={status} error={err}"
        )


def _safe_details(details):
    """Strip non-JSON-serializable objects from the evaluator's details dict."""
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
