#!/usr/bin/env python3
"""Shared helpers for the standalone evaluation pipeline scripts.

Provides:
- project root / path resolution
- agent script loader (dynamic import of run(query, input_payload))
- test case loader
- unified JSON output writer
- timestamp / output-dir resolution
"""
from __future__ import annotations

import importlib.util
import json
import os
import sys
import time
import traceback
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

BASE_DIR = Path(__file__).resolve().parent.parent
TEST_CASES_PATH = BASE_DIR / "eval_data" / "test_cases.json"
SELECTION_PATH = BASE_DIR / "eval_data" / "selection.json"
# Materialized by the web platform when a DB-backed agent / eval set is chosen
# on the 持续评测 page. The pipeline reads these fresh each run (same pattern
# as selection.json), so switching target on the web page takes effect on the
# next Trigger without restarting PikoCI. When absent, the built-in defaults
# (eval_data/test_cases.json + example_agent.py) are used.
RUNTIME_DIR = BASE_DIR / "instance" / "pipeline"
ACTIVE_CASES_PATH = RUNTIME_DIR / "cases.json"
ACTIVE_AGENT_PATH = RUNTIME_DIR / "agent.json"
# Adapter script that dispatches run() to whatever agent is described in
# ACTIVE_AGENT_PATH (uploaded script / HTTP API / built-in example).
AGENT_ADAPTER = BASE_DIR / "scripts" / "pipeline_agent.py"

TOOLS = ("deepeval", "promptfoo", "trulens", "ragas")


def project_root() -> Path:
    return BASE_DIR


def ensure_on_path() -> None:
    """Ensure the project root is on sys.path so app.* imports work."""
    root = str(BASE_DIR)
    if root not in sys.path:
        sys.path.insert(0, root)


def resolve_test_cases_path() -> Path:
    """Pick the test cases file for this run.

    Precedence: explicit ``$EVAL_CASES`` > the web-platform materialized
    ``instance/pipeline/cases.json`` > the built-in ``eval_data/test_cases.json``.
    """
    env = os.environ.get("EVAL_CASES")
    if env:
        return Path(env)
    if ACTIVE_CASES_PATH.exists():
        return ACTIVE_CASES_PATH
    return TEST_CASES_PATH


def load_test_cases(path: Optional[Path] = None) -> List[Dict[str, Any]]:
    """Load the unified test cases JSON."""
    p = path or resolve_test_cases_path()
    with open(p, "r", encoding="utf-8") as f:
        cases = json.load(f)
    if not isinstance(cases, list):
        raise ValueError(f"Test cases file {p} must contain a JSON array")
    return cases


def load_selection(path: Optional[Path] = None) -> Dict[str, Any]:
    """Load the tool/metric selection file.

    Controls which tools run and which metrics are evaluated when Trigger is
    clicked. The file is read fresh on every script invocation, so edits made
    just before triggering take effect without restarting PikoCI.

    Shape (all sections optional; missing => everything enabled)::

        {
          "deepeval":  {"enabled": true,  "metrics": ["task_completion", ...]},
          "promptfoo": {"enabled": true,  "metrics": ["contains", ...]},
          "trulens":   {"enabled": false, "metrics": []}
        }

    A tool with enabled=false is skipped entirely. A tool with an empty/
    missing metrics list runs every metric configured on its cases.
    """
    if path is not None:
        p = path
    elif os.environ.get("EVAL_SELECTION"):
        p = Path(os.environ["EVAL_SELECTION"])
    else:
        p = SELECTION_PATH
    if not p.exists():
        return {}
    try:
        with open(p, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (json.JSONDecodeError, OSError) as exc:
        print(f"[selection] WARN: cannot read {p}: {exc}", file=sys.stderr)
        return {}


def tool_enabled(selection: Dict[str, Any], tool: str) -> bool:
    """Return whether a tool should run at all."""
    cfg = selection.get(tool)
    if not isinstance(cfg, dict):
        return True
    return cfg.get("enabled", True)


def metric_enabled(selection: Dict[str, Any], tool: str, metric: Optional[str]) -> bool:
    """Return whether a specific metric should be scored for a tool.

    If the tool is disabled, always False. If no metrics allow-list is
    configured (missing/empty list), all metrics are enabled.
    """
    if not tool_enabled(selection, tool):
        return False
    cfg = selection.get(tool) or {}
    allow = cfg.get("metrics")
    if not allow:
        return True
    return metric in allow


def filter_cases_for_tool(
    cases: List[Dict[str, Any]], selection: Dict[str, Any], tool: str
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Split cases into (to_run, skipped) for a given tool.

    A case is run when the tool is enabled AND the metric configured on that
    case is in the selection's allow-list. Skipped cases carry a ``_skip_reason``
    key explaining why.
    """
    metric_key = "promptfoo_assert" if tool == "promptfoo" else tool
    run: List[Dict[str, Any]] = []
    skipped: List[Dict[str, Any]] = []
    if not tool_enabled(selection, tool):
        for c in cases:
            skipped.append({**c, "_skip_reason": "tool_disabled"})
        return run, skipped

    for c in cases:
        metric_cfg = c.get("metrics", {}).get(metric_key)
        metric = metric_cfg.get("type") if isinstance(metric_cfg, dict) else metric_cfg
        if not metric:
            # Case does not target this tool at all (e.g. a DeepEval-only case
            # from the platform). Mark it skipped rather than running it under
            # a wrong default metric.
            skipped.append({**c, "_skip_reason": "not_configured", "_metric": None})
        elif metric_enabled(selection, tool, metric):
            run.append(c)
        else:
            skipped.append({**c, "_skip_reason": "metric_filtered", "_metric": metric})
    return run, skipped


def resolve_agent_script() -> Path:
    """Resolve the agent script path from $AGENT_SCRIPT.

    Defaults to the adapter (``scripts/pipeline_agent.py``), which dispatches
    to the agent materialized by the web platform. An explicit $AGENT_SCRIPT
    (relative/absolute) is honored for direct/local runs.
    """
    raw = os.environ.get("AGENT_SCRIPT")
    if not raw:
        return AGENT_ADAPTER.resolve()
    p = Path(raw)
    if not p.is_absolute():
        # Try cwd first, then project root
        cwd_candidate = Path.cwd() / p
        if cwd_candidate.exists():
            return cwd_candidate.resolve()
        p = BASE_DIR / p
    return p.resolve()


def agent_label() -> str:
    """Human-readable name of the active agent for logs/reports.

    When the adapter is in use (default or explicitly $AGENT_SCRIPT pointing at
    pipeline_agent.py), read the materialized descriptor's ``name``. An explicit
    custom $AGENT_SCRIPT is shown by its filename.
    """
    raw = os.environ.get("AGENT_SCRIPT", "")
    using_adapter = (not raw) or Path(raw).name == "pipeline_agent.py"
    if using_adapter and ACTIVE_AGENT_PATH.exists():
        try:
            with open(ACTIVE_AGENT_PATH, "r", encoding="utf-8") as f:
                desc = json.load(f)
            name = (desc or {}).get("name")
            if name:
                return str(name)
        except (json.JSONDecodeError, OSError):
            pass
    if raw:
        return Path(raw).name
    return "example_agent.py"


def load_agent_runner(script_path: Optional[Path] = None) -> Callable[..., Any]:
    """Dynamically import an agent script and return its entry function.

    The agent module must expose either ``run(query, input_payload=None)`` or
    ``run_agent(query, input_payload=None)``.
    """
    script_path = script_path or resolve_agent_script()
    if not script_path.exists():
        raise FileNotFoundError(f"Agent script not found: {script_path}")

    spec = importlib.util.spec_from_file_location("pipeline_agent", script_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot load agent spec from {script_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    for attr in ("run", "run_agent"):
        fn = getattr(module, attr, None)
        if callable(fn):
            return fn
    raise AttributeError(
        f"Agent script {script_path} must define a callable 'run' or 'run_agent'"
    )


def call_agent(
    runner: Callable[..., Any], query: str, input_payload: Optional[Dict] = None
) -> Tuple[str, Optional[Dict[str, Any]], float]:
    """Call the agent and normalize its return value.

    Returns (answer_text, payload_dict_or_None, latency_ms).
    """
    t0 = time.perf_counter()
    try:
        # Inspect signature to decide whether to pass input_payload
        try:
            import inspect

            sig = inspect.signature(runner)
            if len(sig.parameters) >= 2:
                raw = runner(query, input_payload)
            else:
                raw = runner(query)
        except (ValueError, TypeError):
            raw = runner(query, input_payload)
    except Exception as exc:  # noqa: BLE001
        elapsed_ms = round((time.perf_counter() - t0) * 1000, 2)
        return f"Agent调用失败: {exc}", None, elapsed_ms

    elapsed_ms = round((time.perf_counter() - t0) * 1000, 2)

    if isinstance(raw, dict):
        answer = raw.get("answer")
        if answer is None:
            answer = str(raw)
        return str(answer), raw, elapsed_ms
    return str(raw), None, elapsed_ms


def resolve_output_dir() -> Path:
    """Return the eval output directory from $EVAL_OUTPUT_DIR, creating it."""
    raw = os.environ.get("EVAL_OUTPUT_DIR")
    if not raw:
        ts = datetime.now().strftime("%Y%m%d-%H%M%S")
        raw = str(BASE_DIR / "eval_output" / ts)
    out = Path(raw)
    out.mkdir(parents=True, exist_ok=True)
    return out


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def write_tool_results(
    output_dir: Path,
    tool: str,
    cases: List[Dict[str, Any]],
    duration_s: float,
    extra: Optional[Dict[str, Any]] = None,
) -> Path:
    """Write a per-tool results JSON in the unified schema.

    ``cases`` is a list of dicts with at least:
    id, name, query, metric, agent_output, expected, score, status, error, latency_ms, details
    """
    passed = sum(1 for c in cases if c.get("status") == "passed")
    failed = sum(1 for c in cases if c.get("status") == "failed")
    skipped = sum(1 for c in cases if c.get("status") == "skipped")
    # Only scored (non-skipped) cases feed the average; skipped have no score.
    scored = [
        c for c in cases
        if c.get("score") is not None and c.get("status") != "skipped"
    ]
    avg = round(sum(c["score"] for c in scored) / len(scored), 2) if scored else None

    payload: Dict[str, Any] = {
        "tool": tool,
        "timestamp": now_iso(),
        "total": len(cases),
        "passed": passed,
        "failed": failed,
        "skipped": skipped,
        "avg_score": avg,
        "duration_s": round(duration_s, 2),
        "cases": cases,
    }
    if extra:
        payload.update(extra)

    path = output_dir / f"{tool}_results.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2, default=str)
    return path


def build_case_record(
    case: Dict[str, Any],
    metric: str,
    agent_output: str,
    score: Optional[float],
    status: str,
    error: Optional[str],
    latency_ms: float,
    details: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Build a single case result record in the unified schema."""
    return {
        "id": case.get("id", ""),
        "name": case.get("name", ""),
        "query": case.get("query", ""),
        "metric": metric,
        "agent_output": agent_output or "",
        "expected": case.get("expected", ""),
        "score": round(score, 2) if score is not None else None,
        "status": status,
        "error": error,
        "latency_ms": round(latency_ms, 2),
        "details": details or {},
    }


def safe(fn: Callable[[], Any], label: str) -> Any:
    """Run a callable, printing a traceback and exiting on failure."""
    try:
        return fn()
    except Exception as exc:  # noqa: BLE001
        print(f"[ERROR] {label}: {exc}", file=sys.stderr)
        traceback.print_exc()
        sys.exit(1)
