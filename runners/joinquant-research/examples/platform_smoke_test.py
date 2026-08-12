"""Short real-platform validation for the JoinQuant Research runner."""

from pathlib import Path

from research_runner import ResearchRunner, RunnerConfig, get_price


ASSETS = ["510300.XSHG", "510500.XSHG"]


def target_weights(context):
    scores = []
    for code in ASSETS:
        frame = get_price(
            code,
            count=21,
            end_date=context.observation_date,
            frequency="daily",
            fields=["close"],
            skip_paused=True,
            panel=False,
            fq="pre",
        )
        if frame is None or len(frame) < 21:
            continue
        first = float(frame["close"].iloc[0])
        last = float(frame["close"].iloc[-1])
        if first > 0:
            scores.append((last / first - 1.0, code))
    winner = sorted(scores, reverse=True)[0][1] if scores else ASSETS[0]
    return {winner: 1.0}


def run():
    config = RunnerConfig(
        start_date="2024-01-02",
        end_date="2024-03-29",
        initial_cash=1_000_000,
        frequency="monthly",
        schedule_when="first",
        execution_price="open",
        run_id="platform-smoke-20240812-v4",
    )
    result = ResearchRunner(config, target_weights).run()
    output = Path("exports") / config.run_id
    manifest = result.export(
        output,
        strategy_id="joinquant-research-runner-smoke",
        variant="baseline",
        source_path=Path(__file__),
    )
    print("JOINQUANT_RESEARCH_RUNNER_SMOKE_OK")
    print(manifest["metrics"])
    print("bundle={}".format(str(output) + ".zip"))
    return result, manifest, Path(str(output) + ".zip")


if __name__ == "__main__":
    run()
