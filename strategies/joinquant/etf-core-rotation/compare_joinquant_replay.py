"""Compare the frozen local baseline with the JoinQuant Research full replay."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import matplotlib
import numpy as np
import pandas as pd


matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402


DEFENSIVE_SYMBOL = "511880.XSHG"
TRADING_DAYS_PER_YEAR = 250


def normalize_symbol(symbol: str) -> str:
    value = str(symbol).strip()
    if value.startswith("SH") and len(value) == 8:
        return f"{value[2:]}.XSHG"
    if value.startswith("SZ") and len(value) == 8:
        return f"{value[2:]}.XSHE"
    return value


def parse_symbols(value: object) -> set[str]:
    if pd.isna(value) or not str(value).strip():
        return set()
    return {normalize_symbol(item) for item in str(value).split(";") if item}


def parse_weights(value: object) -> dict[str, float]:
    if pd.isna(value) or not str(value).strip():
        return {}
    raw = json.loads(str(value))
    return {normalize_symbol(symbol): float(weight) for symbol, weight in raw.items()}


def jaccard(left: set[str], right: set[str]) -> float:
    union = left | right
    return len(left & right) / len(union) if union else 1.0


def weight_l1(left: dict[str, float], right: dict[str, float]) -> float:
    return sum(abs(left.get(symbol, 0.0) - right.get(symbol, 0.0)) for symbol in left | right)


def annualized_return(total_values: pd.Series) -> float:
    if len(total_values) < 2 or float(total_values.iloc[0]) <= 0:
        return float("nan")
    return float((total_values.iloc[-1] / total_values.iloc[0]) ** (TRADING_DAYS_PER_YEAR / (len(total_values) - 1)) - 1)


def compare_frames(
    local_decisions: pd.DataFrame,
    replay_decisions: pd.DataFrame,
    local_equity: pd.DataFrame,
    replay_equity: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, object]]:
    local = local_decisions.copy()
    replay = replay_decisions.copy()
    for frame in (local, replay):
        frame["observation_date"] = pd.to_datetime(frame["observation_date"])
        frame["execution_date"] = pd.to_datetime(frame["execution_date"])
    decisions = local.merge(
        replay,
        on="observation_date",
        how="inner",
        suffixes=("_local", "_jq"),
    )
    rows = []
    for item in decisions.itertuples(index=False):
        local_selected = parse_symbols(item.selected_local)
        jq_selected = parse_symbols(item.selected_jq)
        local_weights = parse_weights(item.target_weights_local)
        jq_weights = parse_weights(item.target_weights_jq)
        rows.append(
            {
                "observation_date": item.observation_date.date().isoformat(),
                "execution_date_local": item.execution_date_local.date().isoformat(),
                "execution_date_jq": item.execution_date_jq.date().isoformat(),
                "universe_count_local": int(item.liquid_count),
                "universe_count_jq": int(item.universe_count),
                "universe_count_difference": int(item.universe_count - item.liquid_count),
                "selected_local": ";".join(sorted(local_selected)),
                "selected_jq": ";".join(sorted(jq_selected)),
                "selected_exact_match": local_selected == jq_selected,
                "selected_jaccard": jaccard(local_selected, jq_selected),
                "target_weight_l1": weight_l1(local_weights, jq_weights),
                "risk_weight_local": 1.0 - local_weights.get(DEFENSIVE_SYMBOL, 0.0),
                "risk_weight_jq": 1.0 - jq_weights.get(DEFENSIVE_SYMBOL, 0.0),
            }
        )
    decision_comparison = pd.DataFrame(rows)

    local_path = local_equity.copy()
    replay_path = replay_equity.copy()
    local_path["date"] = pd.to_datetime(local_path["trade_date"])
    replay_path["date"] = pd.to_datetime(replay_path["date"])
    path = local_path[["date", "total_value", "daily_return"]].merge(
        replay_path[["date", "total_value", "daily_return"]],
        on="date",
        how="inner",
        suffixes=("_local", "_jq"),
    )
    first_common_execution = decisions["execution_date_local"].min()
    path = path[path["date"] >= first_common_execution].copy()
    for side in ("local", "jq"):
        path[f"normalized_value_{side}"] = (
            path[f"total_value_{side}"] / path[f"total_value_{side}"].iloc[0]
        )
    path["daily_return_difference"] = path["daily_return_jq"] - path["daily_return_local"]
    path["normalized_value_difference"] = path["normalized_value_jq"] - path["normalized_value_local"]

    schedule_exact = decision_comparison["execution_date_local"].eq(
        decision_comparison["execution_date_jq"]
    )
    aggregate: dict[str, object] = {
        "local_decisions": int(len(local)),
        "joinquant_decisions": int(len(replay)),
        "matched_observation_dates": int(len(decision_comparison)),
        "extra_joinquant_start_boundary_decisions": int(len(replay) - len(decision_comparison)),
        "execution_date_exact_match_ratio": float(schedule_exact.mean()),
        "selected_exact_match_ratio": float(decision_comparison["selected_exact_match"].mean()),
        "mean_selected_jaccard": float(decision_comparison["selected_jaccard"].mean()),
        "mean_target_weight_l1": float(decision_comparison["target_weight_l1"].mean()),
        "mean_abs_universe_count_difference": float(
            decision_comparison["universe_count_difference"].abs().mean()
        ),
        "mean_abs_risk_weight_difference": float(
            (decision_comparison["risk_weight_jq"] - decision_comparison["risk_weight_local"]).abs().mean()
        ),
        "matched_equity_days_from_first_common_execution": int(len(path)),
        "daily_return_correlation": float(path["daily_return_local"].corr(path["daily_return_jq"])),
        "daily_return_mean_absolute_difference": float(path["daily_return_difference"].abs().mean()),
        "annualized_active_return_tracking_error": float(
            path["daily_return_difference"].std(ddof=1) * np.sqrt(TRADING_DAYS_PER_YEAR)
        ),
        "local_annualized_return_common_window": annualized_return(path["total_value_local"]),
        "joinquant_annualized_return_common_window": annualized_return(path["total_value_jq"]),
        "ending_normalized_value_local": float(path["normalized_value_local"].iloc[-1]),
        "ending_normalized_value_joinquant": float(path["normalized_value_jq"].iloc[-1]),
    }
    return decision_comparison, path, aggregate


def compare_paths(local_run: Path, replay_run: Path, output_dir: Path) -> dict[str, object]:
    decisions, equity, aggregate = compare_frames(
        pd.read_csv(local_run / "raw" / "baseline-decisions.csv"),
        pd.read_csv(replay_run / "raw" / "decisions.csv"),
        pd.read_csv(local_run / "raw" / "baseline-equity.csv"),
        pd.read_csv(replay_run / "raw" / "equity.csv"),
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    decisions.to_csv(output_dir / "replay-decision-comparison.csv", index=False)
    equity.to_csv(output_dir / "replay-equity-comparison.csv", index=False)
    (output_dir / "replay-comparison.json").write_text(
        json.dumps(aggregate, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return aggregate


def plot_path_comparison(path: pd.DataFrame, output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig, axes = plt.subplots(2, 1, figsize=(11, 7.5), sharex=True)
    axes[0].plot(path["date"], path["normalized_value_local"], label="Local static profile")
    axes[0].plot(path["date"], path["normalized_value_jq"], label="JoinQuant PIT profile")
    axes[0].set_ylabel("Normalized value")
    axes[0].set_title("ETF Core Rotation v1: local vs JoinQuant Research")
    axes[0].grid(alpha=0.25)
    axes[0].legend()
    axes[1].plot(path["date"], path["normalized_value_difference"], color="#b24a3b")
    axes[1].axhline(0.0, color="black", linewidth=0.8)
    axes[1].set_ylabel("JoinQuant - local")
    axes[1].set_xlabel("Date")
    axes[1].grid(alpha=0.25)
    fig.tight_layout()
    fig.savefig(output_path, dpi=160)
    plt.close(fig)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--local-run", required=True, type=Path)
    parser.add_argument("--replay-run", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--asset-dir", type=Path)
    args = parser.parse_args()
    decisions, path, result = compare_frames(
        pd.read_csv(args.local_run / "raw" / "baseline-decisions.csv"),
        pd.read_csv(args.replay_run / "raw" / "decisions.csv"),
        pd.read_csv(args.local_run / "raw" / "baseline-equity.csv"),
        pd.read_csv(args.replay_run / "raw" / "equity.csv"),
    )
    args.output_dir.mkdir(parents=True, exist_ok=True)
    decisions.to_csv(args.output_dir / "replay-decision-comparison.csv", index=False)
    path.to_csv(args.output_dir / "replay-equity-comparison.csv", index=False)
    (args.output_dir / "replay-comparison.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    if args.asset_dir is not None:
        plot_path_comparison(path, args.asset_dir / "platform-path-comparison.png")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
