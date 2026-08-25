#!/usr/bin/env python3
"""Pipeline agent adapter.

The PikoCI pipeline always points ``$AGENT_SCRIPT`` at this file. It reads a
small descriptor (``instance/pipeline/agent.json``, materialized by the web
platform when an agent is chosen on the 持续评测 page) and dispatches a
``run(query, input_payload=None)`` call to the real agent — whether that is an
uploaded Python script, an HTTP API agent, or a local module.

This module deliberately has NO Flask / database dependency: it only reads the
materialized JSON, so the standalone evaluation scripts (DeepEval / Promptfoo /
TruLens) can import it the same way they imported a plain agent script before.

Descriptor shape (all fields optional)::

    {
      "name": "weather-agent",          # for logs / report display
      "access_type": "script|api|local|default",
      "script_path": "/abs/path/agent.py",   # script
      "entry_function": "run",               # script/local
      "module": "example_agent",             # local
      "api_endpoint": "http://...",          # api
      "api_method": "POST",
      "api_headers": {"Authorization": "..."},
      "api_request_mapping": {...},
      "api_response_mapping": {"result_path": "data.answer"},
      "timeout": 120
    }

When no descriptor exists, the built-in ``example_agent.py`` is used.

Agent contract (same as before): ``run(query, input_payload=None) -> str | dict``
where a dict may carry an ``answer`` key.
"""
from __future__ import annotations

import importlib
import importlib.util
import inspect
import json
import os
import sys
from pathlib import Path
from typing import Any, Callable, Dict, Optional

BASE_DIR = Path(__file__).resolve().parent.parent
DESCRIPTOR_PATH = BASE_DIR / "instance" / "pipeline" / "agent.json"


def _load_descriptor() -> Dict[str, Any]:
    path = os.environ.get("PIPELINE_AGENT") or str(DESCRIPTOR_PATH)
    p = Path(path)
    if not p.exists():
        return {"access_type": "default", "name": "example_agent.py"}
    try:
        with open(p, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (json.JSONDecodeError, OSError) as exc:
        print(f"[pipeline_agent] WARN: cannot read {p}: {exc}", file=sys.stderr)
        return {}


def _load_script(script_path: str, entry_function: str) -> Callable[..., Any]:
    p = Path(script_path)
    if not p.is_absolute():
        cwd_candidate = Path.cwd() / p
        p = cwd_candidate if cwd_candidate.exists() else BASE_DIR / p
    if not p.exists():
        raise FileNotFoundError(f"Agent script not found: {p}")

    spec = importlib.util.spec_from_file_location("pipeline_custom_agent", p)
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot load agent spec from {p}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    for attr in (entry_function or "", "run", "run_agent"):
        fn = getattr(module, attr, None) if attr else None
        if callable(fn):
            return fn
    raise AttributeError(
        f"Agent script {p} must define '{entry_function}'/'run'/'run_agent'"
    )


def _load_local(module_name: str, entry_function: str) -> Callable[..., Any]:
    if not module_name:
        raise ValueError("local agent requires a module name")
    module = importlib.import_module(module_name)
    for attr in (entry_function or "", "run", "run_agent"):
        fn = getattr(module, attr, None) if attr else None
        if callable(fn):
            return fn
    raise AttributeError(f"Module {module_name} has no callable entry function")


def _call_func(fn: Callable[..., Any], query: str, input_payload: Any) -> Any:
    try:
        sig = inspect.signature(fn)
        if len(sig.parameters) >= 2 and input_payload is not None:
            return fn(query, input_payload)
    except (ValueError, TypeError):
        pass
    return fn(query)


def _call_api(desc: Dict[str, Any], query: str, input_payload: Any) -> Any:
    import requests  # local import: only needed for API agents

    endpoint = desc.get("api_endpoint")
    if not endpoint:
        raise ValueError("api agent has no api_endpoint")
    method = (desc.get("api_method") or "POST").upper()
    timeout = float(desc.get("timeout") or os.environ.get("AGENT_API_TIMEOUT") or 120)

    headers = dict(desc.get("api_headers") or {})
    mapping = desc.get("api_request_mapping")
    if mapping:
        payload: Dict[str, Any] = {}
        for key, value in mapping.items():
            if value == "{query}":
                payload[key] = query
            elif value == "{input_payload}" and input_payload:
                payload[key] = input_payload
            elif value == "{query_with_payload}" and input_payload:
                payload[key] = {"query": query, **(input_payload or {})}
            else:
                payload[key] = value
    else:
        payload = {"query": query}
        if input_payload:
            payload["input_payload"] = input_payload

    if method == "GET":
        resp = requests.get(endpoint, params=payload, headers=headers, timeout=timeout)
    else:
        resp = requests.post(endpoint, json=payload, headers=headers, timeout=timeout)
    resp.raise_for_status()
    data = resp.json()

    result_path = (desc.get("api_response_mapping") or {}).get("result_path")
    if result_path:
        for key in str(result_path).split("."):
            if isinstance(data, dict) and key in data:
                data = data[key]
            else:
                break
    return data


# Descriptor loaded once per process (the pytest/promptfoo/trulens workers each
# call run() many times; no need to re-read the file per call).
_DESC = _load_descriptor()
_FN: Optional[Callable[..., Any]] = None


def _runner() -> Callable[..., Any]:
    global _FN
    if _FN is not None:
        return _FN
    access = (_DESC.get("access_type") or "default").lower()
    if access == "script":
        _FN = _load_script(_DESC.get("script_path", ""), _DESC.get("entry_function", "run"))
    elif access == "local":
        _FN = _load_local(_DESC.get("module", ""), _DESC.get("entry_function", "run_agent"))
    elif access == "api":
        _FN = lambda query, input_payload=None: _call_api(_DESC, query, input_payload)  # noqa: E731
    else:
        # default: built-in example agent
        _FN = _load_script(str(BASE_DIR / "example_agent.py"), "run")
    return _FN


def run(query: str, input_payload: Any = None) -> Any:
    """Entry point used by the evaluation scripts (run(query, input_payload))."""
    return _call_func(_runner(), query, input_payload)


if __name__ == "__main__":
    # Manual smoke test: python scripts/pipeline_agent.py "你好"
    q = sys.argv[1] if len(sys.argv) > 1 else "你好"
    result = run(q, None)
    if isinstance(result, dict):
        print(result.get("answer", result))
    else:
        print(result)
