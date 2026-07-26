import importlib.util
import sys
from pathlib import Path


MODULE_PATH = Path(__file__).resolve().parents[1] / "crawler.py"
SPEC = importlib.util.spec_from_file_location("joinquant_crawler", MODULE_PATH)
assert SPEC and SPEC.loader
crawler = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = crawler
SPEC.loader.exec_module(crawler)


def test_source_hint_wins_over_reference_link():
    text = """# 参考：https://www.joinquant.com/post/111
# 克隆自聚宽文章：https://www.joinquant.com/post/222
"""
    urls = crawler.extract_joinquant_urls(text)
    selected, method = crawler.choose_primary_url(text, urls)
    assert selected == "https://www.joinquant.com/post/222"
    assert method == "source_hint"


def test_extract_urls_deduplicates_and_strips_chinese_punctuation():
    text = (
        "https://www.joinquant.com/post/30806，"
        "再见 https://www.joinquant.com/post/30806。"
    )
    assert crawler.extract_joinquant_urls(text) == ["https://www.joinquant.com/post/30806"]


def test_normalize_strategy_name():
    assert crawler.normalize_strategy_name("98.欧奈尔CANSLIM策略初探三.txt") == "欧奈尔CANSLIM策略初探三"
    assert crawler.normalize_strategy_name("20小盘股动态调仓.py") == "小盘股动态调仓"


def test_extract_local_header():
    title, author = crawler.extract_local_header(
        "# 克隆自聚宽文章：https://www.joinquant.com/post/45671\n"
        "# 标题：低代码迁移成本的实盘方案:jqtrade+one quant\n"
        "# 作者：拉姆达投资\n"
    )
    assert title == "低代码迁移成本的实盘方案:jqtrade+one quant"
    assert author == "拉姆达投资"


def test_inventory_only_includes_files_below_category_directories(tmp_path):
    (tmp_path / "必看！好评送好礼.txt").write_text("促销说明", encoding="utf-8")
    category = tmp_path / "2025年度精选策略"
    category.mkdir()
    strategy = category / "1.示例策略.txt"
    strategy.write_text(
        "# 克隆自聚宽文章：https://www.joinquant.com/post/123\n",
        encoding="utf-8",
    )

    items = crawler.inventory_source_files(tmp_path, {".txt", ".py"})

    assert [item.relative_path for item in items] == [
        Path("2025年度精选策略") / "1.示例策略.txt"
    ]


def test_parse_summary_page_extracts_configuration_and_duplicate_ids():
    page = """
    <input type="hidden" id="backtestId" value="encrypted-id">
    <input type="hidden" id="backtestId" value="12345">
    <input type="hidden" id="postId" value="30806">
    <input type="hidden" id="backtestType" value="0">
    <input type="hidden" id="backtestId-decryptId" value="12345">
    <span id="startDate">2005-05-01</span>
    <span id="endDate">2020-12-18</span>
    <span id="baseCapital">￥100,000</span>
    <span id="frequency" value="day">每天</span>
    <script>var pythonVersion = 3</script>
    <div class="jq-c-cloneCount">282</div>
    """
    parsed = crawler.parse_summary_page(page)
    assert parsed["start_date"] == "2005-05-01"
    assert parsed["end_date"] == "2020-12-18"
    assert parsed["base_capital"] == 100000
    assert parsed["frequency_code"] == "day"
    assert parsed["frequency_label"] == "每天"
    assert parsed["page_backtest_ids"] == ["encrypted-id", "12345"]
    assert parsed["numeric_backtest_id"] == "12345"
    assert parsed["python_version"] == 3
    assert parsed["clone_count"] == 282


def test_sanitize_post_drops_email_and_ip_fields():
    post = {
        "title": "策略",
        "clientIp": "127.0.0.1",
        "author": {
            "userId": "u1",
            "alias": "作者",
            "email": "private@example.com",
            "euid": "secret",
        },
    }
    sanitized = crawler.sanitize_post(post)
    assert sanitized["title"] == "策略"
    assert "clientIp" not in sanitized
    assert sanitized["author"] == {"userId": "u1", "alias": "作者"}


def test_display_metrics_converts_ratios_to_percent():
    display = crawler.display_metrics(
        {
            "algorithm_return": 1.5,
            "max_drawdown": 0.25,
            "sharpe": 1.2,
        }
    )
    assert display["algorithm_return_percent"] == 150.0
    assert display["max_drawdown_percent"] == 25.0
    assert display["sharpe"] == 1.2
