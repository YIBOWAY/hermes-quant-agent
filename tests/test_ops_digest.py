from __future__ import annotations

from hqa.ops_digest import DIGEST_CONTRACT, build_ops_digest


def test_digest_maps_canaries_to_chinese_trial_sleeves() -> None:
    def fetch(path: str):
        if path.startswith("/api/health"):
            return 200, {
                "safety": {"live_trading_enabled": False, "kill_switch": True},
                "hermes_command_ledger": {
                    "admission_mode": "local_trust",
                    "chat_write_ready": True,
                },
            }
        if path.startswith("/api/safety"):
            return 200, {
                "d34": {"research_routing": {"default_research_entry": "d33"}},
                "soak": {"completed_cycles": 2, "required_completed_cycles": 10},
            }
        if path.startswith("/api/hermes/canaries"):
            return 200, {
                "items": [
                    {
                        "canary_id": "canary-test",
                        "status": "running",
                        "allocated_cash": "10000.00",
                        "daily_pnl": "0.00",
                    }
                ]
            }
        if path.startswith("/api/hermes/research/jobs"):
            return 200, {"items": []}
        raise AssertionError(path)

    digest = build_ops_digest(fetch=fetch)
    assert digest["contract"] == DIGEST_CONTRACT
    assert digest["research"]["trial_sleeves"][0]["label"] == "纸面试运行仓"
    assert digest["safety"]["live_trading_enabled"] is False
    assert "纸面试运行仓" in digest["next_action"]


def test_digest_does_not_invent_a_default_research_cycle() -> None:
    def fetch(path: str):
        if path.startswith("/api/health"):
            return 200, {
                "safety": {"live_trading_enabled": False, "kill_switch": True},
                "hermes_command_ledger": {
                    "admission_mode": "local_trust",
                    "chat_write_ready": True,
                },
            }
        if path.startswith("/api/safety"):
            return 200, {
                "d34": {"research_routing": {"default_research_entry": "d33"}},
                "soak": {"completed_cycles": 1, "required_completed_cycles": 10},
            }
        if path.startswith("/api/hermes/canaries"):
            return 200, {"items": []}
        if path.startswith("/api/hermes/research/jobs"):
            return 200, {"items": []}
        raise AssertionError(path)

    digest = build_ops_digest(fetch=fetch)
    assert "不会自行开周期" in digest["next_action"]
