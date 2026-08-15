"""Compare local ETF snapshots with JoinQuant point-in-time golden probe output."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd


def _symbols(value: object) -> set[str]:
    if value is None or pd.isna(value) or str(value).strip() == "":
        return set()
    return {item for item in str(value).split(";") if item}


def _weights(value: object) -> dict[str, float]:
    if value is None or pd.isna(value) or str(value).strip() == "":
        return {}
    return {str(key): float(weight) for key, weight in json.loads(str(value)).items()}


def _jaccard(left: set[str], right: set[str]) -> float:
    union = left | right
    return len(left & right) / len(union) if union else 1.0


def compare_frames(
    local_summary: pd.DataFrame,
    local_members: pd.DataFrame,
    jq_summary: pd.DataFrame,
    jq_members: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    summary_rows = []
    member_rows = []
    dates = sorted(
        set(local_summary["observation_date"]).intersection(jq_summary["observation_date"])
    )
    for date in dates:
        local_s = local_summary[local_summary["observation_date"].eq(date)].iloc[0]
        jq_s = jq_summary[jq_summary["observation_date"].eq(date)].iloc[0]
        local_m = local_members[local_members["observation_date"].eq(date)].copy()
        jq_m = jq_members[jq_members["observation_date"].eq(date)].copy()
        local_set = set(local_m["symbol"])
        jq_set = set(jq_m["symbol"])
        common = local_set & jq_set
        local_top3 = set(local_m.nsmallest(3, "rank")["symbol"])
        jq_top3 = set(jq_m.nsmallest(3, "rank")["symbol"])
        local_top10 = set(local_m.nsmallest(10, "rank")["symbol"])
        jq_top10 = set(jq_m.nsmallest(10, "rank")["symbol"])
        local_selected = _symbols(local_s.get("selected"))
        jq_selected = _symbols(jq_s.get("selected"))
        local_weights = _weights(local_s.get("target_weights"))
        jq_weights = _weights(jq_s.get("target_weights"))
        weight_union = set(local_weights) | set(jq_weights)
        weight_l1 = sum(
            abs(local_weights.get(symbol, 0.0) - jq_weights.get(symbol, 0.0))
            for symbol in weight_union
        )
        merged = local_m.merge(
            jq_m,
            on=["observation_date", "symbol"],
            suffixes=("_local", "_jq"),
            how="inner",
        )
        rank_corr = (
            float(merged[["rank_local", "rank_jq"]].corr(method="spearman").iloc[0, 1])
            if len(merged) >= 2
            else np.nan
        )
        summary_rows.append(
            {
                "observation_date": date,
                "local_count": len(local_set),
                "joinquant_count": len(jq_set),
                "common_count": len(common),
                "universe_jaccard": _jaccard(local_set, jq_set),
                "local_covered_by_joinquant": len(common) / len(local_set) if local_set else 1.0,
                "joinquant_covered_by_local": len(common) / len(jq_set) if jq_set else 1.0,
                "top3_jaccard": _jaccard(local_top3, jq_top3),
                "top10_jaccard": _jaccard(local_top10, jq_top10),
                "selected_jaccard": _jaccard(local_selected, jq_selected),
                "selected_exact_match": local_selected == jq_selected,
                "target_weight_l1": weight_l1,
                "common_rank_spearman": rank_corr,
                "median_abs_r63_diff": float((merged["r63_local"] - merged["r63_jq"]).abs().median()),
                "median_abs_r126_diff": float(
                    (merged["r126_local"] - merged["r126_jq"]).abs().median()
                ),
                "median_abs_r252_diff": float(
                    (merged["r252_local"] - merged["r252_jq"]).abs().median()
                ),
                "median_abs_vol60_diff": float(
                    (merged["vol60_local"] - merged["vol60_jq"]).abs().median()
                ),
                "median_adv20_relative_diff": float(
                    (
                        (merged["adv20_local"] - merged["adv20_jq"]).abs()
                        / merged["adv20_jq"].abs().replace(0, np.nan)
                    ).median()
                ),
            }
        )
        for _, row in merged.iterrows():
            member_rows.append(
                {
                    "observation_date": date,
                    "symbol": row["symbol"],
                    "rank_local": int(row["rank_local"]),
                    "rank_joinquant": int(row["rank_jq"]),
                    "rank_difference": int(row["rank_local"] - row["rank_jq"]),
                    "score_local": float(row["score_local"]),
                    "score_joinquant": float(row["score_jq"]),
                    "r63_difference": float(row["r63_local"] - row["r63_jq"]),
                    "r126_difference": float(row["r126_local"] - row["r126_jq"]),
                    "r252_difference": float(row["r252_local"] - row["r252_jq"]),
                    "vol60_difference": float(row["vol60_local"] - row["vol60_jq"]),
                    "adv20_relative_difference": float(
                        (row["adv20_local"] - row["adv20_jq"]) / row["adv20_jq"]
                    ),
                }
            )
    summary = pd.DataFrame(summary_rows)
    members = pd.DataFrame(member_rows)
    aggregate = {
        "matched_dates": int(len(summary)),
        "mean_universe_jaccard": float(summary["universe_jaccard"].mean()),
        "median_universe_jaccard": float(summary["universe_jaccard"].median()),
        "mean_top3_jaccard": float(summary["top3_jaccard"].mean()),
        "mean_top10_jaccard": float(summary["top10_jaccard"].mean()),
        "selected_exact_match_ratio": float(summary["selected_exact_match"].mean()),
        "mean_selected_jaccard": float(summary["selected_jaccard"].mean()),
        "mean_target_weight_l1": float(summary["target_weight_l1"].mean()),
        "median_common_rank_spearman": float(summary["common_rank_spearman"].median()),
        "median_abs_r63_diff": float(summary["median_abs_r63_diff"].median()),
        "median_abs_r126_diff": float(summary["median_abs_r126_diff"].median()),
        "median_abs_r252_diff": float(summary["median_abs_r252_diff"].median()),
        "median_abs_vol60_diff": float(summary["median_abs_vol60_diff"].median()),
        "median_adv20_relative_diff": float(summary["median_adv20_relative_diff"].median()),
    }
    return summary, members, aggregate


def run(run_dir: Path) -> dict:
    raw = Path(run_dir) / "raw"
    local = raw / "local"
    jq = raw / "joinquant" / "raw"
    summary, members, aggregate = compare_frames(
        pd.read_csv(local / "local-probe-summary.csv"),
        pd.read_csv(local / "local-probe-members.csv"),
        pd.read_csv(jq / "joinquant-probe-summary.csv"),
        pd.read_csv(jq / "joinquant-probe-members.csv"),
    )
    summary.to_csv(raw / "platform-comparison-summary.csv", index=False)
    members.to_csv(raw / "platform-comparison-members.csv", index=False)
    (raw / "platform-comparison.json").write_text(
        json.dumps(aggregate, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return aggregate


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_dir", type=Path)
    args = parser.parse_args()
    print(json.dumps(run(args.run_dir), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
