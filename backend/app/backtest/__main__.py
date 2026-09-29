"""python -m app.backtest --start 2026-08-01 --end 2026-09-28 [--step-hours 24] [--name NAME]"""

import argparse
from datetime import UTC, datetime

from app.backtest.runner import run_backtest
from app.core.config import get_settings
from app.db.session import get_session_factory


def _date(value: str) -> datetime:
    return datetime.fromisoformat(value).replace(tzinfo=UTC)


def main() -> None:
    p = argparse.ArgumentParser(description="Replay a past window through the paper engine.")
    p.add_argument("--start", type=_date, required=True)
    p.add_argument("--end", type=_date, required=True)
    p.add_argument("--step-hours", type=int, default=24)
    p.add_argument("--name")
    a = p.parse_args()
    run_id = run_backtest(
        get_session_factory(), get_settings(), start=a.start, end=a.end,
        step_hours=a.step_hours, name=a.name,
    )  # fmt: skip
    print(f"backtest {run_id} finished; see /backtests")  # noqa: T201


if __name__ == "__main__":
    main()
