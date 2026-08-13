"""One-screen operator digest. Read-only. No trading, no provider calls."""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any
from urllib.error import URLError
from urllib.request import Request, urlopen

DIGEST_CONTRACT = "hqa.ops_digest/v1"
DEFAULT_BACKEND = "http://127.0.0.1:8765"


def _get_json(url: str, timeout: float = 4.0) -> tuple[int, Any]:
    request = Request(url, method="GET")
    try:
        with urlopen(request, timeout=timeout) as response:
            body = response.read().decode("utf-8")
            return response.status, json.loads(body)
    except URLError as exc:
        return 0, {"error": str(exc.reason if hasattr(exc, "reason") else exc)}
    except TimeoutError:
        return 0, {"error": "timeout"}
    except json.JSONDecodeError:
        return 0, {"error": "invalid_json"}


def build_ops_digest(
    *,
    backend: str = DEFAULT_BACKEND,
    fetch: Callable[[str], tuple[int, Any]] | None = None,
) -> dict[str, Any]:
    getter = fetch or (lambda path: _get_json(backend.rstrip("/") + path))
    health_status, health = getter("/api/health")
    safety_status, safety = getter("/api/safety/effective/v2?workspace_id=default")
    canary_status, canaries = getter("/api/hermes/canaries?workspace_id=default")
    job_status, jobs = getter("/api/hermes/research/jobs?workspace_id=default")

    ledger = health.get("hermes_command_ledger", {}) if isinstance(health, dict) else {}
    safety_body = safety if isinstance(safety, dict) else {}
    d34 = safety_body.get("d34", {}) if isinstance(safety_body, dict) else {}
    soak = safety_body.get("soak", {}) if isinstance(safety_body, dict) else {}
    canary_items = canaries.get("items", []) if isinstance(canaries, dict) else []
    job_items = jobs.get("items", []) if isinstance(jobs, dict) else []
    exceptions = [
        {
            "job_id": item.get("job_id"),
            "state": item.get("state"),
            "outcome_code": item.get("outcome_code"),
        }
        for item in job_items
        if isinstance(item, dict)
        and item.get("state") in {"rejected", "outcome_unknown", "cancelled"}
    ]
    trial_sleeves = [
        {
            "id": item.get("canary_id"),
            "status": item.get("status"),
            "cash": item.get("allocated_cash"),
            "pnl": item.get("daily_pnl"),
            "label": "纸面试运行仓",
        }
        for item in canary_items
        if isinstance(item, dict)
    ]
    next_action = "无待办：有研究需求时再提出，系统不会自行开周期"
    if ledger.get("chat_write_ready") is not True:
        next_action = "对话写入门关闭：先确认 connector 心跳"
    elif exceptions:
        next_action = f"处理 {len(exceptions)} 条研究异常后再提出新研究"
    elif trial_sleeves and all(item.get("pnl") in {None, "0", "0.00", "+$0.00", 0} for item in trial_sleeves):
        next_action = "纸面试运行仓仍是现金：看冻结账户是否挡住成交"

    return {
        "contract": DIGEST_CONTRACT,
        "probes": {
            "health": health_status,
            "safety": safety_status,
            "canaries": canary_status,
            "jobs": job_status,
        },
        "safety": {
            "live_trading_enabled": (health.get("safety") or {}).get("live_trading_enabled")
            if isinstance(health, dict)
            else None,
            "kill_switch": (health.get("safety") or {}).get("kill_switch")
            if isinstance(health, dict)
            else None,
            "admission_mode": ledger.get("admission_mode"),
            "chat_write_ready": ledger.get("chat_write_ready"),
        },
        "research": {
            "default_entry": (d34.get("research_routing") or {}).get("default_research_entry")
            if isinstance(d34, dict)
            else soak.get("default_research_entry")
            if isinstance(soak, dict)
            else None,
            "completed_cycles": soak.get("completed_cycles") if isinstance(soak, dict) else None,
            "required_cycles": soak.get("required_completed_cycles")
            if isinstance(soak, dict)
            else None,
            "trial_sleeves": trial_sleeves,
            "exceptions": exceptions,
        },
        "next_action": next_action,
    }
