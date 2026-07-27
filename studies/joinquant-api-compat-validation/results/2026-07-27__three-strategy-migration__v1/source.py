"""用同一聚宽兼容层验收价格、ETF 与基本面三类策略逻辑。"""

from __future__ import annotations

import hashlib
import json
import shutil
import sys
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from quant_research.data.store import ResearchDataStore  # noqa: E402
from quant_research.jq_compat import JoinQuantCompat  # noqa: E402
from quant_research.portal import (  # noqa: E402
    CompositeDailyBarSource,
    LocalDataPortal,
    PartitionedDailyBarSource,
    QlibDailyBarSource,
)


OBSERVATION_DATE = pd.Timestamp("2026-07-23")
RESULT = (
    Path(__file__).parent
    / "results"
    / "2026-07-27__three-strategy-migration__v1"
)


def index_timing_logic(api: JoinQuantCompat) -> dict:
    prices = api.get_price(
        "000300.XSHG",
        end_date=OBSERVATION_DATE,
        count=60,
        frequency="daily",
        fields=["close"],
        panel=False,
    )
    close = prices["close"].astype(float)
    return {
        "observations": len(close),
        "last_close": float(close.iloc[-1]),
        "ma20": float(close.tail(20).mean()),
        "risk_on": bool(close.iloc[-1] > close.tail(20).mean()),
    }


def etf_rotation_logic(api: JoinQuantCompat) -> pd.DataFrame:
    symbols = ["510300.XSHG", "510500.XSHG", "513100.XSHG", "518880.XSHG"]
    closes = api.history(
        20,
        "1d",
        "close",
        symbols,
        df=True,
        skip_paused=False,
        fq="pre",
    )
    momentum = closes.iloc[-1] / closes.iloc[0] - 1.0
    momentum.index.name = "symbol"
    return momentum.rename("momentum_20d").sort_values(ascending=False).reset_index()


def fundamental_quality_logic(api: JoinQuantCompat) -> pd.DataFrame:
    symbols = ["600000.XSHG", "600519.XSHG", "000001.XSHE", "000858.XSHE"]
    frame = api.get_fundamentals(
        symbols,
        fields=["revenue", "parent_net_profit", "roe", "basic_eps"],
        date=OBSERVATION_DATE,
    )
    local_to_jq = {
        "SH600000": "600000.XSHG",
        "SH600519": "600519.XSHG",
        "SZ000001": "000001.XSHE",
        "SZ000858": "000858.XSHE",
    }
    frame["jq_symbol"] = frame["symbol"].map(local_to_jq)
    current = api.get_current_data()
    frame["tradable"] = [
        not current[code].paused and current[code].is_st is False
        for code in frame["jq_symbol"]
    ]
    return frame.sort_values("roe", ascending=False).reset_index(drop=True)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    if RESULT.exists():
        raise FileExistsError(f"immutable validation archive already exists: {RESULT}")
    raw = RESULT / "raw"
    raw.mkdir(parents=True)
    store = ResearchDataStore()
    daily_bars = CompositeDailyBarSource(
        store,
        QlibDailyBarSource(),
        {"etf": PartitionedDailyBarSource(store, "etf_daily")},
    )
    portal = LocalDataPortal(store, daily_bars)
    api = JoinQuantCompat(portal, OBSERVATION_DATE)

    timing = index_timing_logic(api)
    timing_provenance = api.last_query_provenance.copy()
    etf = etf_rotation_logic(api)
    etf_provenance = api.last_query_provenance.copy()
    fundamentals = fundamental_quality_logic(api)
    fundamental_provenance = api.last_query_provenance.copy()
    etf.to_csv(raw / "etf-ranking.csv", index=False, encoding="utf-8-sig")
    fundamentals.to_csv(raw / "fundamental-ranking.csv", index=False, encoding="utf-8-sig")
    (raw / "index-timing.json").write_text(
        json.dumps(timing, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    shutil.copy2(__file__, RESULT / "source.py")
    checks = {
        "index_60_sessions": timing["observations"] == 60,
        "etf_four_ranked": len(etf) == 4 and etf["momentum_20d"].notna().all(),
        "fundamental_four_visible": len(fundamentals) == 4,
        "notice_dates_point_in_time": bool(
            pd.to_datetime(fundamentals["notice_date"]).le(OBSERVATION_DATE).all()
        ),
        "all_three_have_provenance": all(
            item and item.get("quality_grade")
            for item in (timing_provenance, etf_provenance, fundamental_provenance)
        ),
    }
    source_path = RESULT / "source.py"
    manifest = {
        "schema_version": 1,
        "study": "joinquant-api-compat-validation",
        "observation_date": OBSERVATION_DATE.strftime("%Y-%m-%d"),
        "status": "passed" if all(checks.values()) else "failed",
        "checks": checks,
        "strategies": {
            "index_timing": timing,
            "etf_rotation_top": etf.iloc[0].to_dict(),
            "fundamental_quality_top": fundamentals.iloc[0][
                ["jq_symbol", "roe", "notice_date"]
            ].astype(str).to_dict(),
        },
        "provenance": {
            "index_timing": timing_provenance,
            "etf_rotation": etf_provenance,
            "fundamental_quality": fundamental_provenance,
        },
        "source_sha256": _sha256(source_path),
        "raw_sha256": {
            path.name: _sha256(path) for path in sorted(raw.iterdir())
        },
        "limitations": [
            "本验收证明三类策略共享查询层，不是收益黄金对照；收益对照分别属于迭代2、5、6。",
            "聚宽query DSL不模拟，基本面策略显式传入symbols和fields。",
        ],
    }
    (RESULT / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, default=str) + "\n",
        encoding="utf-8",
    )
    (RESULT / "report.md").write_text(
        "# 聚宽日频兼容层三策略验收\n\n"
        f"观察日：{OBSERVATION_DATE:%Y-%m-%d}。\n\n"
        "同一 `JoinQuantCompat` 实例依次执行指数60日均线择时、四ETF动量轮动、"
        "四股票公告日基本面质量排序；未为三类逻辑各写一套数据读取代码。\n\n"
        f"机器检查：`{json.dumps(checks, ensure_ascii=False)}`。\n\n"
        "本轮只验收接口迁移与点时语义；策略收益黄金对照不在此报告中冒充完成。\n",
        encoding="utf-8",
    )
    print(json.dumps(manifest, ensure_ascii=False, indent=2, default=str))
    return 0 if manifest["status"] == "passed" else 2


if __name__ == "__main__":
    raise SystemExit(main())
