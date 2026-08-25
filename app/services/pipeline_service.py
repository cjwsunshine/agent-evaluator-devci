"""Service for the PikoCI-backed continuous-evaluation page.

Bridges the web platform and the standalone evaluation pipeline:

- Reads/writes ``eval_data/selection.json`` (which tools + metrics to run).
- Drives the ``pikoci`` CLI to trigger builds and poll their status/logs.
- Locates the latest generated HTML report.

The PikoCI server itself runs separately (``./pikoci server ...``). This
service talks to it over its local HTTP API via the bundled ``pikoci``
binary, so the web platform does not need to speak PikoCI's API directly.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
from pathlib import Path
from typing import Any

from app.config.config import Config

# ---------------------------------------------------------------------------
# Paths and constants
# ---------------------------------------------------------------------------

BASE_DIR = Path(Config.BASE_DIR)
SELECTION_PATH = BASE_DIR / "eval_data" / "selection.json"
TEST_CASES_PATH = BASE_DIR / "eval_data" / "test_cases.json"
EVAL_OUTPUT_DIR = BASE_DIR / "eval_output"
# Runtime materialization: when the web page picks a platform Agent + 评测集,
# we write a normalized agent descriptor + cases file here. The pipeline's
# scripts read these fresh each run (see scripts/eval_common.py), so the change
# takes effect on the next Trigger without restarting PikoCI.
RUNTIME_DIR = BASE_DIR / "instance" / "pipeline"
TARGET_PATH = RUNTIME_DIR / "target.json"
ACTIVE_CASES_PATH = RUNTIME_DIR / "cases.json"
ACTIVE_AGENT_PATH = RUNTIME_DIR / "agent.json"
# Built-in agent / cases used when nothing has been picked on the page yet.
BUILTIN_AGENT = {"id": "builtin", "name": "example_agent.py (内置示例)", "access_type": "default"}
BUILTIN_CASES = {"id": "builtin", "name": "内置示例用例 (eval_data/test_cases.json)", "count": None}
PIKOCI_BIN = str(BASE_DIR / "pikoci")

# PikoCI connection settings. Read from the runtime config (system settings page,
# persisted to instance/system_config.json) with environment variables as fallback
# at access time — so they can be changed on the settings page without restarting.
_PIKOCI_DEFAULTS = {
    "pikoci_url": os.environ.get("PIKOCI_URL", "http://localhost:8080"),
    "pikoci_team": os.environ.get("PIKOCI_TEAM", "main"),
    "pikoci_pipeline": os.environ.get("PIKOCI_PIPELINE", "agent-eval"),
    "pikoci_job": os.environ.get("PIKOCI_JOB", "evaluate"),
    "pikoci_user": os.environ.get("PIKOCI_USER", "admin"),
    "pikoci_pass": os.environ.get("PIKOCI_PASS", "admin123"),
}


def _pikoci_conf(key: str) -> str:
    try:
        runtime = Config.get_runtime_config()
        value = runtime.get(key)
        if value not in (None, ""):
            return value
    except Exception:
        pass
    return _PIKOCI_DEFAULTS.get(key, "")

# Metric catalog shown in the UI (name -> human label). Only metrics that are
# meaningful selectors for the pipeline's test cases are listed; an empty
# selection list means "run all metrics", so users are not forced to enumerate.
METRIC_CATALOG: dict[str, list[dict[str, str]]] = {
    "deepeval": [
        {"name": "task_completion", "label": "任务完成度"},
        {"name": "tool_correctness", "label": "工具调用正确性"},
        {"name": "hallucination", "label": "幻觉率"},
        {"name": "factual_consistency", "label": "事实一致性"},
        {"name": "goal_accuracy", "label": "目标准确性"},
        {"name": "format_compliance", "label": "格式合规率"},
        {"name": "geval", "label": "自定义GEval评分"},
        {"name": "plan_quality", "label": "规划合理性 (需trace)"},
        {"name": "plan_adherence", "label": "指令遵循度 (需trace)"},
        {"name": "step_efficiency", "label": "步骤效率 (需trace)"},
        # —— 预置 GEval 指标（固化评分准则，Ark LLM 当裁判，直接勾选即用）——
        {"name": "completeness", "label": "完整度"},
        {"name": "conciseness", "label": "简洁度"},
        {"name": "safety_harm", "label": "有害内容(安全度)"},
        {"name": "unauthorized_access", "label": "越权防护"},
        {"name": "prompt_injection_resistance", "label": "Prompt注入抵御"},
        {"name": "ambiguity_handling", "label": "歧义处理"},
        {"name": "boundary_robustness", "label": "边界值鲁棒性"},
        {"name": "tool_selection", "label": "工具选择"},
        {"name": "tool_argument_accuracy", "label": "参数正确性"},
        {"name": "tool_call_efficiency", "label": "工具调用效率(次数)"},
        {"name": "trajectory_coherence", "label": "轨迹连贯 (需trace)"},
        {"name": "error_recovery", "label": "错误恢复 (需trace)"},
        {"name": "multi_turn_coherence", "label": "多轮上下文理解 (需messages)"},
    ],
    "trulens": [
        {"name": "answer_relevance", "label": "回答相关性"},
        {"name": "context_relevance", "label": "上下文相关性"},
        {"name": "groundedness", "label": "事实一致性(groundedness)"},
    ],
    "promptfoo": [
        {"name": "contains", "label": "包含关键词 (contains)"},
        {"name": "not-contains", "label": "不含关键词 (not-contains)"},
        {"name": "contains-any", "label": "包含任一 (contains-any)"},
        {"name": "similar", "label": "语义相似 (similar)"},
        {"name": "llm-rubric", "label": "LLM评分 (llm-rubric)"},
        {"name": "python", "label": "Python断言 (python)"},
    ],
    "ragas": [
        {"name": "answer_relevancy", "label": "回答相关性"},
        {"name": "faithfulness", "label": "忠实度/事实一致性"},
        {"name": "answer_correctness", "label": "回答正确性 (需reference)"},
        {"name": "context_precision", "label": "上下文精确率 (需context+reference)"},
        {"name": "context_recall", "label": "上下文召回率 (需context+reference)"},
        {"name": "context_entity_recall", "label": "上下文实体召回 (需context+reference)"},
        {"name": "noise_sensitivity", "label": "噪声敏感性 (需context+reference)"},
    ],
}

TOOL_LABELS = {
    "deepeval": "DeepEval",
    "promptfoo": "Promptfoo",
    "trulens": "TruLens",
    "ragas": "RAGAS",
}

# Terminal build statuses (we stop polling once one of these is reached).
_TERMINAL_STATUS = {"succeeded", "failed", "errored", "cancelled", "canceled"}


# ---------------------------------------------------------------------------
# Selection file
# ---------------------------------------------------------------------------

def _default_selection() -> dict[str, Any]:
    return {
        tool: {"enabled": True, "metrics": []} for tool in METRIC_CATALOG
    }


def load_selection() -> dict[str, Any]:
    """Read selection.json, filling in any missing tool sections."""
    data: dict[str, Any] = {}
    if SELECTION_PATH.exists():
        try:
            with open(SELECTION_PATH, "r", encoding="utf-8") as f:
                loaded = json.load(f)
            if isinstance(loaded, dict):
                data = loaded
        except (json.JSONDecodeError, OSError):
            data = {}

    merged = _default_selection()
    for tool in METRIC_CATALOG:
        cfg = data.get(tool)
        if not isinstance(cfg, dict):
            continue
        merged[tool] = {
            "enabled": bool(cfg.get("enabled", True)),
            "metrics": list(cfg.get("metrics") or []),
        }
    return merged


def save_selection(payload: dict[str, Any]) -> dict[str, Any]:
    """Validate and persist the selection from the web form.

    ``payload`` maps tool name to ``{"enabled": bool, "metrics": [...],
    "all_metrics": bool}``. When ``all_metrics`` is true we store an empty
    list (== run every metric for that tool).
    """
    current = load_selection()
    for tool, catalog in METRIC_CATALOG.items():
        section = payload.get(tool)
        if not isinstance(section, dict):
            continue
        allowed = {m["name"] for m in catalog}
        enabled = bool(section.get("enabled", True))
        if section.get("all_metrics"):
            metrics: list[str] = []
        else:
            raw_metrics = section.get("metrics") or []
            metrics = [m for m in raw_metrics if m in allowed]
        current[tool] = {"enabled": enabled, "metrics": metrics}

    SELECTION_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(SELECTION_PATH, "w", encoding="utf-8") as f:
        json.dump(current, f, ensure_ascii=False, indent=2)
    return current


def _metrics_in_use() -> dict[str, list[str]]:
    """Compute which metrics the active test cases actually exercise, per tool.

    Reads whatever cases file is currently materialized (the selected 评测集,
    or the built-in default), so the "在用" hints match what this Trigger will
    actually run.
    """
    used: dict[str, set[str]] = {t: set() for t in METRIC_CATALOG}
    cases_path = ACTIVE_CASES_PATH if ACTIVE_CASES_PATH.exists() else TEST_CASES_PATH
    try:
        with open(cases_path, "r", encoding="utf-8") as f:
            cases = json.load(f)
    except (OSError, json.JSONDecodeError):
        return {t: [] for t in METRIC_CATALOG}

    for case in cases if isinstance(cases, list) else []:
        metrics = (case or {}).get("metrics") or {}
        for tool in METRIC_CATALOG:
            key = "promptfoo_assert" if tool == "promptfoo" else tool
            cfg = metrics.get(key)
            if isinstance(cfg, dict):
                name = cfg.get("type")
            else:
                name = cfg
            if name:
                used[tool].add(str(name))
    return {t: sorted(s) for t, s in used.items()}


def get_selection_view() -> dict[str, Any]:
    """Full payload for the web page: selection + catalog + in-use hints."""
    selection = load_selection()
    in_use = _metrics_in_use()
    tools = []
    for tool, catalog in METRIC_CATALOG.items():
        cfg = selection[tool]
        metrics = cfg["metrics"]
        tools.append({
            "key": tool,
            "label": TOOL_LABELS[tool],
            "enabled": cfg["enabled"],
            "all_metrics": len(metrics) == 0,
            "metrics": metrics,
            "in_use": in_use.get(tool, []),
            "catalog": catalog,
        })
    return {
        "tools": tools,
        "pikoci_url": _pikoci_conf("pikoci_url"),
        "pipeline": _pikoci_conf("pikoci_pipeline"),
        "job": _pikoci_conf("pikoci_job"),
    }


# ---------------------------------------------------------------------------
# Targets: which platform Agent + 评测集 the pipeline evaluates
# ---------------------------------------------------------------------------

# Maps the platform's per-tool metric names onto the pipeline metric names so
# the selected set maps cleanly onto the pipeline engines. The pipeline's
# DeepEval/TruLens/RAGAS evaluators accept the canonical names below;
# platform-only metrics (e.g. red_team) fall through to their raw name.
_TOOL_METRIC_DEFAULTS = {
    "deepeval": "task_completion",
    "trulens": "answer_relevance",
    "ragas": "answer_relevancy",
}


def _agents_for_user(user_id) -> list[dict[str, Any]]:
    from app.models.models import Agent
    # The CI build runs host-side (not as the requesting user), so the target
    # picker lists every active Agent in the platform.
    agents = Agent.query.order_by(Agent.created_at.desc()).all()
    out = []
    for a in agents:
        if not a.is_active and a.access_type == "script" and not a.script_file:
            continue
        out.append({
            "id": str(a.id),
            "name": a.name,
            "version": a.version or "",
            "access_type": a.access_type,
            "detail": _agent_detail(a),
        })
    return out


def _agent_detail(a) -> str:
    if a.access_type == "script":
        return a.script_file or "未上传脚本"
    if a.access_type == "api":
        return a.api_endpoint or "未配置地址"
    if a.access_type == "local":
        cfg = json.loads(a.access_config) if a.access_config else {}
        return cfg.get("module", "未配置模块") if isinstance(cfg, dict) else "未配置模块"
    return a.access_type or ""


def list_targets(user_id) -> dict[str, Any]:
    """Return selectable agents + evaluation sets, plus the active target."""
    from app.services.test_case_service import TestCaseService
    agents = [dict(BUILTIN_AGENT)] + _agents_for_user(user_id)
    sets_resp = TestCaseService.get_evaluation_sets(user_id)
    sets: list[dict[str, Any]] = [dict(BUILTIN_CASES)]
    if sets_resp.get("success"):
        for s in sets_resp["data"]:
            sets.append({
                "id": str(s["id"]),
                "name": s["name"],
                "count": s.get("test_case_count", 0),
                "tool": s.get("evaluation_tool"),
                "metric": s.get("metric"),
                "agent_name": s.get("agent_name"),
            })
    return {
        "agents": agents,
        "evaluation_sets": sets,
        "active": _load_target(),
    }


def _load_target() -> dict[str, Any]:
    if not TARGET_PATH.exists():
        return {"agent_id": "builtin", "evalset_id": "builtin",
                "agent_name": BUILTIN_AGENT["name"], "evalset_name": BUILTIN_CASES["name"]}
    try:
        with open(TARGET_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {"agent_id": "builtin", "evalset_id": "builtin"}


def _agent_descriptor(agent) -> dict[str, Any]:
    """Build the scripts/pipeline_agent.py descriptor for a platform Agent."""
    desc: dict[str, Any] = {"name": agent.name, "access_type": agent.access_type}
    if agent.access_type == "script":
        if not agent.script_file:
            raise ValueError(f"Agent「{agent.name}」未上传脚本")
        script_path = str((BASE_DIR / "agents_uploads" / agent.script_file).resolve())
        if not os.path.exists(script_path):
            raise ValueError(f"Agent 脚本文件不存在：{agent.script_file}")
        desc["script_path"] = script_path
        desc["entry_function"] = agent.entry_function or "run"
    elif agent.access_type == "api":
        if not agent.api_endpoint:
            raise ValueError(f"Agent「{agent.name}」未配置 API 地址")
        desc["api_endpoint"] = agent.api_endpoint
        desc["api_method"] = agent.api_method or "POST"
        desc["api_headers"] = agent.api_headers or {}
        desc["api_request_mapping"] = agent.api_request_mapping
        desc["api_response_mapping"] = agent.api_response_mapping
        try:
            cfg = json.loads(agent.access_config) if agent.access_config else {}
            if isinstance(cfg, dict) and cfg.get("timeout"):
                desc["timeout"] = cfg["timeout"]
        except (json.JSONDecodeError, TypeError):
            pass
    elif agent.access_type == "local":
        cfg = json.loads(agent.access_config) if agent.access_config else {}
        if not isinstance(cfg, dict) or not cfg.get("module"):
            raise ValueError(f"Agent「{agent.name}」未配置本地模块")
        desc["module"] = cfg["module"]
        desc["entry_function"] = cfg.get("function", agent.entry_function or "run_agent")
    else:
        raise ValueError(f"不支持的 Agent 接入类型：{agent.access_type}")
    return desc


def _db_case_to_pipeline(case) -> dict[str, Any]:
    """Convert a platform TestCase row into the pipeline case schema."""
    tool = (case.evaluation_tool or "deepeval").lower()
    metric = case.metric or _TOOL_METRIC_DEFAULTS.get(tool, "task_completion")
    metrics: dict[str, Any] = {}
    if tool == "promptfoo":
        # The standalone pipeline drives promptfoo via assertion config; the
        # platform's promptfoo metrics (e.g. red_team) don't map 1:1, so fall
        # back to a "contains <expected>" assertion to keep the set runnable.
        metrics["promptfoo_assert"] = {"type": "contains", "value": case.expected or ""}
    else:
        metrics[tool] = metric
    return {
        "id": f"case-{case.id}",
        "name": case.name or f"case-{case.id}",
        "query": case.query or "",
        "expected": case.expected or "",
        "input_payload": case.input_payload,
        "expected_payload": case.expected_payload,
        "metrics": metrics,
    }


def _cases_for_evalset(user_id, evalset_id: str) -> list[dict[str, Any]]:
    from app.models.models import EvaluationSet, TestCase
    if evalset_id == "builtin":
        with open(TEST_CASES_PATH, "r", encoding="utf-8") as f:
            return json.load(f)

    if str(evalset_id).startswith("orphan-"):
        # Virtual grouping produced by TestCaseService: orphan-<agent_id>-<tool>::<metric>
        parts = str(evalset_id).split("::", 1)
        base = parts[0].split("-", 2)
        if len(base) != 3 or base[0] != "orphan":
            raise ValueError("评测集不存在")
        _, agent_id_text, tool = base
        metric_text = parts[1] if len(parts) == 2 else "none"
        q = TestCase.query.filter_by(user_id=user_id, set_id=None, evaluation_tool=tool)
        q = q.filter(TestCase.metric.is_(None) if metric_text == "none" else TestCase.metric == metric_text)
        if agent_id_text == "none":
            q = q.filter(TestCase.agent_id.is_(None))
        else:
            q = q.filter_by(agent_id=int(agent_id_text))
        rows = q.all()
    else:
        es = EvaluationSet.query.filter_by(id=int(evalset_id), user_id=user_id).first()
        if not es:
            raise ValueError("评测集不存在")
        rows = list(es.test_cases)

    if not rows:
        raise ValueError("所选评测集没有用例")
    return [_db_case_to_pipeline(c) for c in rows]


def save_target(user_id, agent_id: str, evalset_id: str) -> dict[str, Any]:
    """Materialize the chosen agent + cases to instance/pipeline/ for the build.

    Mirrors selection.json: written by the web page, read fresh by the pipeline.
    """
    from app.models.models import Agent
    RUNTIME_DIR.mkdir(parents=True, exist_ok=True)

    # --- agent ---
    if agent_id == "builtin":
        descriptor = {"name": BUILTIN_AGENT["name"], "access_type": "default"}
        agent_name = BUILTIN_AGENT["name"]
    else:
        agent = Agent.query.filter_by(id=int(agent_id)).first()
        if not agent:
            raise ValueError("Agent 不存在")
        descriptor = _agent_descriptor(agent)
        agent_name = agent.name

    # --- cases ---
    cases = _cases_for_evalset(user_id, evalset_id)
    if evalset_id == "builtin":
        evalset_name = BUILTIN_CASES["name"]
    else:
        from app.models.models import EvaluationSet
        es = EvaluationSet.query.filter_by(id=int(evalset_id)).first()
        evalset_name = es.name if es else f"评测集 #{evalset_id}"

    with open(ACTIVE_AGENT_PATH, "w", encoding="utf-8") as f:
        json.dump(descriptor, f, ensure_ascii=False, indent=2)
    with open(ACTIVE_CASES_PATH, "w", encoding="utf-8") as f:
        json.dump(cases, f, ensure_ascii=False, indent=2)
    target = {
        "agent_id": str(agent_id),
        "evalset_id": str(evalset_id),
        "agent_name": agent_name,
        "evalset_name": evalset_name,
        "case_count": len(cases),
    }
    with open(TARGET_PATH, "w", encoding="utf-8") as f:
        json.dump(target, f, ensure_ascii=False, indent=2)
    return target


# ---------------------------------------------------------------------------
# PikoCI CLI interaction
# ---------------------------------------------------------------------------

def _cli_args(*args: str) -> list[str]:
    return [
        PIKOCI_BIN, "client", *args,
        "--url", _pikoci_conf("pikoci_url"),
        "--team-canonical", _pikoci_conf("pikoci_team"),
        "--pipeline-name", _pikoci_conf("pikoci_pipeline"),
        "--job-name", _pikoci_conf("pikoci_job"),
    ]


def _run_cli(args: list[str], *, timeout: int = 60, retry_auth: bool = True) -> tuple[int, str, str]:
    """Run a pikoci client command, logging in first on auth failure."""
    env = os.environ.copy()
    env.setdefault("PROMPTFOO_DISABLE_TELEMETRY", "1")
    proc = subprocess.run(
        args, capture_output=True, text=True, timeout=timeout, env=env
    )
    combined = (proc.stderr or "") + (proc.stdout or "")
    if retry_auth and proc.returncode != 0 and "Authentication required" in combined:
        # Stored JWT is missing/expired — log in once, then retry.
        login = subprocess.run(
            [PIKOCI_BIN, "client", "login", "--url", _pikoci_conf("pikoci_url"),
             "--username", _pikoci_conf("pikoci_user"),
             "--password", _pikoci_conf("pikoci_pass")],
            capture_output=True, text=True, timeout=30, env=env,
        )
        if login.returncode == 0:
            proc = subprocess.run(
                args, capture_output=True, text=True, timeout=timeout, env=env
            )
    return proc.returncode, proc.stdout or "", proc.stderr or ""


def trigger_build() -> dict[str, Any]:
    """Trigger a new evaluate build. Returns the latest build number."""
    rc, out, err = _run_cli(_cli_args("jobs", "trigger"), timeout=60)
    if rc != 0:
        return {"success": False, "message": (err or out or "触发失败").strip()}

    build = _latest_build_number()
    return {
        "success": True,
        "message": "评测已触发",
        "build_number": build,
    }


def _latest_build_number() -> str | None:
    builds = _list_builds(limit=1)
    if builds:
        return str(builds[0].get("build_number"))
    return None


def _list_builds(limit: int = 10) -> list[dict[str, Any]]:
    rc, out, _err = _run_cli(
        _cli_args("builds", "list"), timeout=30, retry_auth=False
    )
    if rc != 0:
        return []
    try:
        data = json.loads(out)
    except json.JSONDecodeError:
        return []
    if not isinstance(data, list):
        return []
    return data[:limit]


_ANSI_RE = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")


def _clean_logs(text: str) -> str:
    return _ANSI_RE.sub("", text or "").strip()


def _build_from_json(out: str) -> dict[str, Any] | None:
    try:
        data = json.loads(out)
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict):
        return None
    return data


def _normalize_build(data: dict[str, Any]) -> dict[str, Any]:
    steps_raw = data.get("steps") or []
    steps = []
    for s in steps_raw:
        if not isinstance(s, dict):
            continue
        duration_ns = s.get("duration") or 0
        steps.append({
            "name": s.get("name", ""),
            "status": s.get("status", ""),
            "duration_s": round(duration_ns / 1_000_000_000, 1) if duration_ns else 0,
            "logs": _clean_logs(s.get("logs") or ""),
        })
    duration_ns = data.get("duration") or 0
    return {
        "build_number": str(data.get("build_number", "")),
        "status": data.get("status", ""),
        "started_at": data.get("started_at", ""),
        "duration_s": round(duration_ns / 1_000_000_000, 1) if duration_ns else 0,
        "error": data.get("error") or "",
        "steps": steps,
    }


def list_builds(limit: int = 10) -> list[dict[str, Any]]:
    """Recent builds (without step logs) for the history list."""
    builds = _list_builds(limit=limit)
    result = []
    for b in builds:
        steps_raw = b.get("steps") or []
        result.append({
            "build_number": str(b.get("build_number", "")),
            "status": b.get("status", ""),
            "started_at": b.get("started_at", ""),
            "duration_s": round((b.get("duration") or 0) / 1_000_000_000, 1),

            "step_count": len(steps_raw),
        })
    return result


def get_build(build_number: str | None = None) -> dict[str, Any] | None:
    """Fetch a single build (with step logs). Without a number, the latest."""
    if build_number in (None, "", "latest"):
        builds = _list_builds(limit=1)
        if not builds:
            return None
        build_number = str(builds[0].get("build_number"))

    rc, out, err = _run_cli(
        _cli_args("builds", "get", "--build-number", str(build_number)),
        timeout=30,
    )
    if rc != 0:
        return None
    data = _build_from_json(out)
    if data is None:
        return None
    return _normalize_build(data)


# ---------------------------------------------------------------------------
# Reports
# ---------------------------------------------------------------------------

def latest_report() -> dict[str, Any] | None:
    """Find the newest eval_output/<timestamp>/report.html."""
    reports = list_reports(limit=1)
    return reports[0] if reports else None


def list_reports(limit: int = 20) -> list[dict[str, Any]]:
    """列出磁盘上已生成 HTML 报告的持续评测构建（按时间倒序）。

    每个 run 对应 ``eval_output/<run_id>/``，从其 ``summary.json`` 读取综合分数、
    通过率、各工具状态等。用于平台「评测报告」页展示持续评测历史报告。
    """
    if not EVAL_OUTPUT_DIR.exists():
        return []
    candidates = [
        d for d in EVAL_OUTPUT_DIR.iterdir()
        if d.is_dir() and (d / "report.html").exists()
    ]
    # 按目录修改时间倒序（与 build 完成时间一致）
    candidates.sort(key=lambda d: d.stat().st_mtime, reverse=True)

    reports: list[dict[str, Any]] = []
    for d in candidates[: max(limit, 1)]:
        summary, agent_label, timestamp = _read_run_summary(d)
        overall = summary.get("overall") or {}
        tools = summary.get("tools") or {}
        tool_labels = {
            "deepeval": "DeepEval",
            "promptfoo": "Promptfoo",
            "trulens": "TruLens",
            "ragas": "RAGAS",
        }
        ran_tools = [
            tool_labels.get(t, t)
            for t, v in tools.items()
            if isinstance(v, dict) and v.get("status") == "ok"
        ]
        reports.append({
            "run_id": d.name,
            "report_url": f"/pipeline/report/{d.name}",
            "timestamp": timestamp,
            "mtime": d.stat().st_mtime,
            "agent": agent_label,
            "avg_score": overall.get("avg_score"),
            "pass_rate": overall.get("pass_rate"),
            "total_cases": overall.get("total_cases"),
            "total_passed": overall.get("total_passed"),
            "total_failed": overall.get("total_failed"),
            "total_skipped": overall.get("total_skipped"),
            "tools_run": overall.get("tools_run"),
            "tools": ran_tools,
        })
    return reports


def _read_run_summary(run_dir: Path) -> tuple[dict[str, Any], str, str | None]:
    """读取一个 run 目录的 summary.json，返回 (summary, agent, timestamp)。"""
    summary: dict[str, Any] = {}
    summary_path = run_dir / "summary.json"
    if summary_path.exists():
        try:
            with open(summary_path, "r", encoding="utf-8") as f:
                summary = json.load(f)
        except (json.JSONDecodeError, OSError):
            summary = {}
    agent = summary.get("agent_script") or "未知 Agent"
    timestamp = summary.get("timestamp")
    return summary, str(agent), timestamp
