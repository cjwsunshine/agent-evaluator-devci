#!/usr/bin/env python3
"""Render ``summary.json`` into a single-file HTML report.

The template (``templates/report.html``) uses Jinja2 with Chart.js loaded
from a CDN. The output is fully self-contained (CSS is inlined; only
Chart.js is fetched at view time).

Reads:
    $EVAL_OUTPUT_DIR/summary.json
    ./eval_output/history.jsonl

Writes:
    $EVAL_OUTPUT_DIR/report.html
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from scripts.eval_common import resolve_output_dir  # noqa: E402

TEMPLATE_DIR = BASE_DIR / "templates"
HISTORY_PATH = BASE_DIR / "eval_output" / "history.jsonl"
MAX_HISTORY = 20

# Metrics where a LOW raw score means BETTER (e.g. hallucination 0 = none).
# For charting we flip these into a "health score" (higher = better) so every
# bar reads the same direction.
LOWER_IS_BETTER = {"hallucination", "factual_consistency"}

TOOL_LABELS = {"deepeval": "DeepEval", "promptfoo": "Promptfoo", "trulens": "TruLens", "ragas": "RAGAS"}
TOOL_ORDER = ("deepeval", "promptfoo", "trulens", "ragas")

# Chinese display names for metrics that appear in the test cases.
METRIC_LABELS = {
    "task_completion": "任务完成度",
    "tool_correctness": "工具调用正确性",
    "hallucination": "幻觉率",
    "factual_consistency": "事实一致性",
    "answer_relevance": "回答相关性",
    "context_relevance": "上下文相关性",
    "groundedness": "事实一致性(groundedness)",
    "goal_accuracy": "目标准确性",
    "contains": "包含关键词",
    "not-contains": "不含关键词",
    "contains-any": "包含任一",
    "similar": "语义相似",
    "llm-rubric": "LLM评分",
    "python": "Python断言",
    "answer_relevancy": "回答相关性(RAGAS)",
    "faithfulness": "忠实度(RAGAS)",
    "answer_correctness": "回答正确性(RAGAS)",
    "context_precision": "上下文精确率(RAGAS)",
    "context_recall": "上下文召回率(RAGAS)",
    "context_entity_recall": "上下文实体召回(RAGAS)",
    "noise_sensitivity": "噪声敏感性(RAGAS)",
    "plan_quality": "规划合理性",
    "plan_adherence": "指令遵循度",
    "step_efficiency": "步骤效率",
    # 预置 GEval 指标
    "completeness": "完整度",
    "conciseness": "简洁度",
    "safety_harm": "有害内容(安全度)",
    "unauthorized_access": "越权防护",
    "prompt_injection_resistance": "Prompt注入抵御",
    "ambiguity_handling": "歧义处理",
    "boundary_robustness": "边界值鲁棒性",
    "tool_selection": "工具选择",
    "tool_argument_accuracy": "参数正确性",
    "tool_call_efficiency": "工具调用效率",
    "trajectory_coherence": "轨迹连贯",
    "error_recovery": "错误恢复",
    "multi_turn_coherence": "多轮上下文理解",
}


def _health_score(metric: str | None, score: float | None) -> float | None:
    """Normalize a 0-100 metric score so higher is always better."""
    if score is None:
        return None
    if metric in LOWER_IS_BETTER:
        return max(0.0, 100.0 - float(score))
    return float(score)


def _aggregate_metrics(summary: dict) -> list[dict]:
    """Aggregate per-(tool, metric) scores across all cases.

    Returns a list (in tool order) of rows with the average health score,
    pass/fail counts, and pass rate for each distinct metric. Skipped/not-run
    cases are excluded from the averages.
    """
    tool_order = [t for t in TOOL_ORDER if t in summary.get("tools", {})]
    buckets: dict[tuple[str, str], dict] = {}

    for case in summary.get("cases", []):
        for tool in tool_order:
            r = case.get(tool) or {}
            metric = r.get("metric")
            status = r.get("status")
            if not metric or status in (None, "skipped", "not_run"):
                continue
            raw_score = r.get("score")
            try:
                raw = float(raw_score) if raw_score is not None else None
            except (TypeError, ValueError):
                raw = None
            key = (tool, metric)
            row = buckets.setdefault(key, {
                "tool": tool,
                "metric": metric,
                "label": METRIC_LABELS.get(metric, metric),
                "health_sum": 0.0,
                "health_n": 0,
                "passed": 0,
                "failed": 0,
            })
            hs = _health_score(metric, raw)
            if hs is not None:
                row["health_sum"] += hs
                row["health_n"] += 1
            if status == "passed":
                row["passed"] += 1
            elif status == "failed":
                row["failed"] += 1

    rows = []
    for tool in tool_order:
        for (t, metric), row in buckets.items():
            if t != tool:
                continue
            n = row["health_n"]
            scored = row["passed"] + row["failed"]
            rows.append({
                "tool": tool,
                "tool_label": TOOL_LABELS.get(tool, tool),
                "metric": metric,
                "label": row["label"],
                # Full label shown on the chart axis, grouped by tool.
                "axis_label": f"{TOOL_LABELS.get(tool, tool)} · {row['label']}",
                "avg_health": round(row["health_sum"] / n, 1) if n else None,
                "passed": row["passed"],
                "failed": row["failed"],
                "pass_rate": round(row["passed"] / scored, 4) if scored else None,
                "lower_is_better": metric in LOWER_IS_BETTER,
            })
    return rows


def _per_case_metric_data(summary: dict) -> dict:
    """Build per-case x per-tool health scores for a grouped bar chart.

    Returns a dict with case labels and one dataset per tool (None when the
    tool/metric was skipped or not run for that case).
    """
    tool_order = [t for t in TOOL_ORDER if t in summary.get("tools", {})]
    labels: list[str] = []
    short_labels: list[str] = []
    by_tool: dict[str, list] = {t: [] for t in tool_order}
    rows: list[dict] = []

    for case in summary.get("cases", []):
        name = case.get("name") or case.get("id") or ""
        labels.append(name)
        short_labels.append(case.get("id") or name)
        case_row = {"name": name, "id": case.get("id"), "tools": {}}
        for tool in tool_order:
            r = case.get(tool) or {}
            metric = r.get("metric")
            status = r.get("status")
            raw = r.get("score")
            if status in (None, "skipped", "not_run") or raw is None:
                health = None
            else:
                health = round(_health_score(metric, raw), 1)
            by_tool[tool].append(health)
            case_row["tools"][tool] = {
                "metric": metric,
                "status": status,
                "score": raw,
                "health": health,
                "lower_is_better": metric in LOWER_IS_BETTER,
            }
        rows.append(case_row)

    return {
        "labels": labels,
        "short_labels": short_labels,
        "datasets": [
            {"tool": t, "label": TOOL_LABELS.get(t, t), "data": by_tool[t]}
            for t in tool_order
        ],
        "rows": rows,
        "tool_order": tool_order,
    }


def _load_history(history_path: Path) -> list[dict]:
    if not history_path.exists():
        return []
    rows = []
    with open(history_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return rows[-MAX_HISTORY:]


def _score_class(score: float | None) -> str:
    if score is None:
        return "na"
    if score >= 80:
        return "good"
    if score >= 60:
        return "warn"
    return "bad"


def _status_class(status: str | None) -> str:
    return {
        "passed": "good",
        "failed": "bad",
        "skipped": "na",
        "not_run": "na",
        None: "na",
    }.get(status, "na")


def main() -> int:
    output_dir = resolve_output_dir()
    summary_path = output_dir / "summary.json"
    if not summary_path.exists():
        print(f"[ERROR] summary not found: {summary_path}", file=sys.stderr)
        return 1

    with open(summary_path, "r", encoding="utf-8") as f:
        summary = json.load(f)

    history = _load_history(HISTORY_PATH)

    # Pre-compute chart data
    metric_rows = _aggregate_metrics(summary)
    per_case = _per_case_metric_data(summary)
    tool_names = [t for t in TOOL_ORDER if t in summary["tools"]]
    tool_labels = dict(TOOL_LABELS)
    tool_avg = [
        summary["tools"][t].get("avg_score") or 0 for t in tool_names
    ]
    tool_pass_rate = [
        round((summary["tools"][t].get("pass_rate") or 0) * 100, 1)
        for t in tool_names
    ]

    env = Environment(
        loader=FileSystemLoader(str(TEMPLATE_DIR)),
        autoescape=select_autoescape(["html"]),
    )
    env.filters["score_class"] = _score_class
    env.filters["status_class"] = _status_class
    env.filters["round"] = lambda v, n=2: round(v, n) if isinstance(v, (int, float)) else v
    env.filters["pct"] = lambda v: f"{round(v * 100, 1)}%" if isinstance(v, (int, float)) else "-"

    template = env.get_template("report.html")
    html = template.render(
        summary=summary,
        history=history,
        chart_payload=json.dumps(
            {
                "tool_labels": [tool_labels[t] for t in tool_names],
                "tool_avg": tool_avg,
                "tool_pass_rate": tool_pass_rate,
                "metric_labels": [m["axis_label"] for m in metric_rows],
                "metric_scores": [m["avg_health"] for m in metric_rows],
                "metric_pass_rates": [
                    round((m["pass_rate"] or 0) * 100, 1) if m["pass_rate"] is not None else None
                    for m in metric_rows
                ],
                "metric_tools": [m["tool"] for m in metric_rows],
                "metric_lower_better": [m["lower_is_better"] for m in metric_rows],
                "metric_metrics": [m["metric"] for m in metric_rows],
                "per_case_labels": per_case["labels"],
                "per_case_datasets": per_case["datasets"],
                "per_case_tool_order": per_case["tool_order"],
                "per_case_metric_names": {
                    t: [
                        (case_row["tools"][t]["metric"] if case_row["tools"][t]["status"] not in (None, "skipped", "not_run") else None)
                        for case_row in per_case["rows"]
                    ]
                    for t in per_case["tool_order"]
                },
                "history_labels": [h["timestamp"].replace("T", " ") for h in history],
                "history_avg": [h.get("avg_score") for h in history],
                "history_pass": [
                    round((h.get("pass_rate") or 0) * 100, 1) for h in history
                ],
            }
        ),
        metric_rows=metric_rows,
        per_case_rows=per_case["rows"],
    )

    report_path = output_dir / "report.html"
    with open(report_path, "w", encoding="utf-8") as f:
        f.write(html)

    print(f"[report] wrote {report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
