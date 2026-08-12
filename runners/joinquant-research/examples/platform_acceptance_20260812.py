"""Deterministic platform acceptance entry point; upload with the runner."""

from pathlib import Path

from research_runner import ResearchRunner, RunnerConfig


FIRST_ASSET = "510300.XSHG"
SECOND_ASSET = "510500.XSHG"


def target_weights(context):
    if context.current_date.month == 1:
        return {FIRST_ASSET: 0.5}
    if context.current_date.month == 2:
        return {SECOND_ASSET: 0.5}
    return {}


def run():
    config = RunnerConfig(
        start_date="2024-01-02",
        end_date="2024-03-29",
        initial_cash=1_000_000,
        frequency="monthly",
        schedule_when="first",
        execution_price="open",
        run_id="platform-acceptance-20260812-v5",
    )
    result = ResearchRunner(config, target_weights).run()
    trades = [
        order
        for order in result.orders
        if order["status"] in ("filled", "partial")
    ]
    expected = [
        ("2024-01-02", FIRST_ASSET, "buy"),
        ("2024-02-01", FIRST_ASSET, "sell"),
        ("2024-02-01", SECOND_ASSET, "buy"),
        ("2024-03-01", SECOND_ASSET, "sell"),
    ]
    actual = [(item["date"], item["code"], item["side"]) for item in trades]
    if actual != expected:
        raise AssertionError(
            "unexpected trade sequence: {}; orders={}; warnings={}".format(
                actual, result.orders, result.warnings
            )
        )
    if not all(item["amount"] > 0 and item["amount"] % 100 == 0 for item in trades):
        raise AssertionError("all trades must use positive 100-share lots")
    if not all(item["fees"] > 0 for item in trades):
        raise AssertionError("all acceptance-test trades must include fees")
    if result.positions[-1]["positions"]:
        raise AssertionError("acceptance test must finish with no positions")
    if result.warnings:
        raise AssertionError("platform warnings: {}".format(result.warnings))

    output = Path("exports") / config.run_id
    manifest = result.export(
        output,
        strategy_id="joinquant-research-runner-acceptance",
        variant="fixed-switch-and-exit",
        source_path=Path(__file__),
    )
    bundle = Path(str(output) + ".zip")
    if manifest["artifacts"]["raw/trades.csv"]["rows"] != len(trades):
        raise AssertionError("exported trade row count does not match ledger")
    if not bundle.is_file():
        raise AssertionError("ZIP bundle was not created")

    print("JOINQUANT_RESEARCH_RUNNER_ACCEPTANCE_OK")
    print("trade_count={}".format(len(trades)))
    print(manifest["metrics"])
    print("bundle={}".format(bundle))
    return result, manifest, bundle


if __name__ == "__main__":
    run()
