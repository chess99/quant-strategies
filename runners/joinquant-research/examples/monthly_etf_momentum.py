"""Minimal point-in-time ETF momentum example for JoinQuant Research."""

from pathlib import Path

from jqdata import get_price

from research_runner import ResearchRunner, RunnerConfig


ASSETS = [
    "510300.XSHG",
    "510500.XSHG",
    "159915.XSHE",
    "511010.XSHG",
]


def target_weights(context):
    scores = []
    for code in ASSETS:
        frame = get_price(
            code,
            count=61,
            end_date=context.observation_date,
            frequency="daily",
            fields=["close"],
            skip_paused=True,
            panel=False,
            fq="pre",
        )
        if frame is None or len(frame) < 61:
            continue
        first = float(frame["close"].iloc[0])
        last = float(frame["close"].iloc[-1])
        if first > 0:
            scores.append((last / first - 1.0, code))
    ranked = [item for item in sorted(scores, reverse=True) if item[0] > 0]
    selected = [item[1] for item in ranked[:2]]
    if not selected:
        return {}
    weight = 1.0 / len(selected)
    return {code: weight for code in selected}


def run():
    config = RunnerConfig(
        start_date="2018-01-01",
        end_date="2025-12-31",
        initial_cash=10_000_000,
        frequency="monthly",
        schedule_when="first",
        execution_price="open",
        run_id="monthly-etf-momentum-v1",
    )
    result = ResearchRunner(config, target_weights).run()
    output = Path("exports") / config.run_id
    manifest = result.export(
        output,
        strategy_id="monthly-etf-momentum-example",
        variant="baseline",
        source_path=Path(__file__),
    )
    return result, manifest, Path(str(output) + ".zip")
