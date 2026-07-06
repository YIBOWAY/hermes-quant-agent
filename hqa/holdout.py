from __future__ import annotations

import datetime

# D-21 ②: default 6-month holdout on Scene-B backtests.
# Non-final runs reserve the last HOLDOUT_DAYS so the final window stays unseen
# until the single pre-promotion --final run.

HOLDOUT_DAYS = 183

_HOLDOUT_NOTE = "HOLDOUT: last 183 days reserved; run --final ONCE before promotion (D-21)"


def effective_backtest_end(start: str, end: str, final: bool) -> tuple[str, str]:
    """Resolve the backtest end date given the holdout policy.

    final=True  -> (end, "")            full window, the one pre-promotion run.
    final=False -> (end - HOLDOUT_DAYS ISO, note)  reserve the last 183 days.

    Raises ValueError if the cut end lands on or before start (window too short
    to leave any in-sample room after reserving the holdout).
    """
    if final:
        return end, ""
    start_date = datetime.date.fromisoformat(start)
    end_date = datetime.date.fromisoformat(end)
    cut_date = end_date - datetime.timedelta(days=HOLDOUT_DAYS)
    if cut_date <= start_date:
        raise ValueError(
            f"holdout window too short: cut end {cut_date.isoformat()} <= start {start} "
            f"(need > {HOLDOUT_DAYS} days between start and end)"
        )
    return cut_date.isoformat(), _HOLDOUT_NOTE
