"""Shared pytest fixtures for the DeepEval pipeline tests.

A ``pytest_sessionfinish`` hook converts collected case results into the
unified evaluation schema and writes ``deepeval_results.json`` into
``$EVAL_OUTPUT_DIR``. No third-party pytest plugin is required.
"""
from __future__ import annotations

import json
import os
import sys
import time
import types
from pathlib import Path

import pytest

# Make project root importable so we can reuse app.services.* and scripts.*
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from scripts.eval_common import (  # noqa: E402
    build_case_record,
    call_agent,
    filter_cases_for_tool,
    load_agent_runner,
    load_selection,
    load_test_cases,
    resolve_output_dir,
    write_tool_results,
)

# Module-level cache so test functions and the session-finish hook see the
# same data.
_RESULTS: list[dict] = []
_START_TS: float = time.time()


def _skip_record(case: dict, reason: str) -> dict:
    """Build a 'skipped' case record for a deselected case/tool."""
    metric_cfg = case.get("metrics", {}).get("deepeval")
    metric = metric_cfg.get("type") if isinstance(metric_cfg, dict) else metric_cfg
    label = "工具已关闭" if reason == "tool_disabled" else f"指标 {metric} 未勾选"
    return build_case_record(
        case,
        metric=metric or "",
        agent_output="",
        score=None,
        status="skipped",
        error=label,
        latency_ms=0.0,
        details={"skip_reason": reason},
    )


# Pre-seed skipped records for cases deselected via selection.json so the
# results file always covers every case (skipped vs scored).
_selection = load_selection()
_all_cases = load_test_cases()
_, _skipped_cases = filter_cases_for_tool(_all_cases, _selection, "deepeval")
_RESULTS.extend(_skip_record(c, c.get("_skip_reason", "metric_filtered")) for c in _skipped_cases)


@pytest.fixture(scope="session")
def test_cases():
    return load_test_cases()


@pytest.fixture(scope="session")
def evaluator():
    """A DeepEvalEvaluator that does not touch the database.

    Pattern copied from scripts/verify_metrics.py: pass a SimpleNamespace with
    the attributes the evaluator reads (selected_metrics). score_output()
    does not use Flask or SQLAlchemy.
    """
    from app.services.evaluation_engine import DeepEvalEvaluator

    return DeepEvalEvaluator(types.SimpleNamespace(selected_metrics=[]))


@pytest.fixture(scope="session")
def agent_runner():
    return load_agent_runner()


@pytest.fixture
def record_result():
    """Fixture that returns a callable used to append a case record.

    The test itself calls the evaluator and decides pass/fail via assert;
    this fixture records the outcome so the JSON report can be built at
    session finish regardless of assertion outcome.
    """
    return _record


def _record(record: dict) -> None:
    _RESULTS.append(record)


def pytest_sessionfinish(session, exitstatus):
    """Write unified-schema deepeval_results.json at end of session.

    Uses a core pytest hook (no plugin dependency) so this works whether or
    not ``--json-report`` was passed. The pipeline calls pytest with
    ``--json-report --json-report-file=/dev/null`` so the plugin's own output
    is discarded; our file is the authoritative one.
    """
    if not _RESULTS:
        return
    output_dir = resolve_output_dir()
    duration = round(time.time() - _START_TS, 2)

    write_tool_results(
        output_dir=output_dir,
        tool="deepeval",
        cases=_RESULTS,
        duration_s=duration,
        extra={"pytest_exit_status": int(exitstatus)},
    )
    # Emit a brief summary to stdout for the CI log.
    passed = sum(1 for c in _RESULTS if c["status"] == "passed")
    failed = sum(1 for c in _RESULTS if c["status"] == "failed")
    print(
        f"\n[DeepEval] total={len(_RESULTS)} passed={passed} failed={failed} "
        f"results={output_dir / 'deepeval_results.json'}"
    )
