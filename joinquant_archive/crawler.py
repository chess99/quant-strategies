#!/usr/bin/env python3
"""批量采集本地聚宽策略文件对应的原帖与回测信息。"""

from __future__ import annotations

import argparse
import ast
import csv
import hashlib
import html
import json
import math
import os
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import warnings
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


SCHEMA_VERSION = 1
DEFAULT_SOURCE_ROOT = Path(r"D:\BaiduNetdiskDownload\2020-2026聚宽600条源码")
DEFAULT_OUTPUT_ROOT = Path(__file__).resolve().parent / "data"
DEFAULT_SOURCE_ARCHIVE_ROOT = Path(__file__).resolve().parent / "sources"
CATEGORY_ALIASES = {"2024年度精选策略1": "2024年度精选策略"}
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/138.0.0.0 Safari/537.36"
)
JOINQUANT_URL_RE = re.compile(
    r"https?://(?:www\.)?joinquant\.com/"
    r"(?:post/\d+|view/community/detail/[A-Za-z0-9]+|community/post/detailMobile\?[^\s<>\"']+)",
    re.IGNORECASE,
)
COMMUNITY_ID_RE = re.compile(
    r"(?:/post/|/view/community/detail/)([A-Za-z0-9]+)", re.IGNORECASE
)
SOURCE_HINT_RE = re.compile(r"克隆自聚宽文章|原文(?:链接)?|文章(?:链接|地址)|来源", re.IGNORECASE)
TRAILING_URL_PUNCTUATION = ".,;:!?，。；：！？、)]}）】》>\"'"
SUCCESS_STATUSES = {"ok", "post_without_backtest"}
EMAIL_ADDRESS_RE = re.compile(
    r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE
)
SECRET_ASSIGNMENT_RE = re.compile(
    r"(?P<prefix>\b(?:password|passwd|pwd|secret|token|api[_-]?key|"
    r"access[_-]?key|secret[_-]?key|app[_-]?key)\b\s*[:=]\s*[rubf]*)"
    r"(?P<quote>[\"'])(?P<value>.*?)(?P=quote)",
    re.IGNORECASE,
)


class FetchError(RuntimeError):
    """带请求上下文的网络错误。"""

    def __init__(self, url: str, message: str, status: int | None = None):
        super().__init__(message)
        self.url = url
        self.status = status


@dataclass(frozen=True)
class SourceItem:
    path: Path
    relative_path: Path
    encoding: str
    sha256: str
    size: int
    urls: tuple[str, ...]
    primary_url: str | None
    selection_method: str
    strategy_name: str
    declared_title: str | None
    declared_author: str | None


class RateLimiter:
    """所有工作线程共享的简单全局限速器。"""

    def __init__(self, min_interval: float):
        self.min_interval = max(0.0, min_interval)
        self._lock = threading.Lock()
        self._next_at = 0.0

    def wait(self) -> None:
        with self._lock:
            now = time.monotonic()
            delay = self._next_at - now
            if delay > 0:
                time.sleep(delay)
            self._next_at = max(now, self._next_at) + self.min_interval


class HttpClient:
    def __init__(
        self,
        *,
        timeout: float,
        retries: int,
        min_interval: float,
    ):
        self.timeout = timeout
        self.retries = max(0, retries)
        self.rate_limiter = RateLimiter(min_interval)

    def get(
        self,
        url: str,
        *,
        referer: str | None = None,
        accept: str = "application/json, text/plain, */*",
    ) -> tuple[bytes, str, dict[str, str]]:
        headers = {
            "Accept": accept,
            "User-Agent": USER_AGENT,
            "X-Requested-With": "XMLHttpRequest",
        }
        if referer:
            headers["Referer"] = referer

        last_error: Exception | None = None
        for attempt in range(self.retries + 1):
            self.rate_limiter.wait()
            request = urllib.request.Request(url, headers=headers, method="GET")
            try:
                with urllib.request.urlopen(request, timeout=self.timeout) as response:
                    response_headers = {key.lower(): value for key, value in response.headers.items()}
                    return response.read(), response.geturl(), response_headers
            except urllib.error.HTTPError as exc:
                last_error = exc
                if exc.code not in {408, 425, 429, 500, 502, 503, 504}:
                    raise FetchError(url, f"HTTP {exc.code}", exc.code) from exc
                retry_after = exc.headers.get("Retry-After")
                if retry_after and retry_after.isdigit():
                    time.sleep(min(float(retry_after), 30.0))
            except (urllib.error.URLError, TimeoutError, OSError) as exc:
                last_error = exc
            if attempt < self.retries:
                time.sleep(min(2**attempt, 8))
        raise FetchError(url, f"请求失败：{last_error}") from last_error

    def get_json(self, url: str, *, referer: str | None = None) -> tuple[dict[str, Any], str]:
        body, final_url, _ = self.get(url, referer=referer)
        try:
            payload = json.loads(body.decode("utf-8-sig"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise FetchError(url, f"返回内容不是有效 JSON：{exc}") from exc
        if not isinstance(payload, dict):
            raise FetchError(url, "JSON 顶层不是对象")
        return payload, final_url


def utc_now() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def decode_source(path: Path) -> tuple[str, str, bytes]:
    raw = path.read_bytes()
    for encoding in ("utf-8-sig", "gb18030"):
        try:
            return raw.decode(encoding), encoding, raw
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace"), "utf-8-replace", raw


def clean_url(url: str) -> str:
    return html.unescape(url).rstrip(TRAILING_URL_PUNCTUATION)


def extract_joinquant_urls(text: str) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for match in JOINQUANT_URL_RE.finditer(text):
        url = clean_url(match.group(0))
        if url not in seen:
            seen.add(url)
            result.append(url)
    return result


def choose_primary_url(text: str, urls: Iterable[str]) -> tuple[str | None, str]:
    candidates = list(urls)
    if not candidates:
        return None, "none"

    lines = text.splitlines()
    positions: dict[str, tuple[int, str]] = {}
    for line_number, line in enumerate(lines):
        for url in candidates:
            if url in line and url not in positions:
                positions[url] = (line_number, line)

    scored: list[tuple[int, int, str, str]] = []
    for order, url in enumerate(candidates):
        line_number, line = positions.get(url, (10_000, ""))
        score = 0
        method = "first_community_url"
        if SOURCE_HINT_RE.search(line):
            score += 1000
            method = "source_hint"
        if line_number < 10:
            score += 100
        if "/post/" in url:
            score += 10
        scored.append((score, -order, url, method))
    _, _, selected, method = max(scored)
    return selected, method


def normalize_strategy_name(filename: str) -> str:
    stem = Path(filename).stem.strip()
    stem = re.sub(r"^\s*\d+(?:\.\d+)?[\s.．、_\-]*", "", stem)
    return stem.strip() or Path(filename).stem.strip()


def extract_local_header(text: str) -> tuple[str | None, str | None]:
    header = "\n".join(text.splitlines()[:40])

    def value_for(label: str) -> str | None:
        match = re.search(
            rf"^\s*#?\s*{label}\s*[：:]\s*(.+?)\s*$",
            header,
            re.MULTILINE | re.IGNORECASE,
        )
        return match.group(1).strip() if match else None

    return value_for("标题"), value_for("作者")


def normalize_source_relative_path(relative_path: Path) -> Path:
    parts = list(relative_path.parts)
    if parts:
        parts[0] = CATEGORY_ALIASES.get(parts[0], parts[0])
    return Path(*parts)


def inventory_source_files(source_root: Path, extensions: set[str]) -> list[SourceItem]:
    items: list[SourceItem] = []
    for path in sorted(source_root.rglob("*")):
        if not path.is_file() or path.suffix.lower() not in extensions:
            continue
        # 这个资料集以根目录下的年度分类目录保存策略；根层文件是卖家说明、
        # 交流群图片等附带材料，不属于策略源码。
        if path.parent == source_root:
            continue
        text, encoding, raw = decode_source(path)
        urls = extract_joinquant_urls(text)
        primary_url, selection_method = choose_primary_url(text, urls)
        declared_title, declared_author = extract_local_header(text)
        items.append(
            SourceItem(
                path=path,
                relative_path=normalize_source_relative_path(path.relative_to(source_root)),
                encoding=encoding,
                sha256=hashlib.sha256(raw).hexdigest(),
                size=len(raw),
                urls=tuple(urls),
                primary_url=primary_url,
                selection_method=selection_method,
                strategy_name=normalize_strategy_name(path.name),
                declared_title=declared_title,
                declared_author=declared_author,
            )
        )
    return apply_local_title_fallback(items)


def _title_key(value: str) -> str:
    return re.sub(r"[\W_]+", "", value, flags=re.UNICODE).casefold()


def apply_local_title_fallback(items: list[SourceItem]) -> list[SourceItem]:
    title_to_urls: dict[str, set[str]] = {}
    for item in items:
        if item.primary_url:
            title_to_urls.setdefault(_title_key(item.strategy_name), set()).add(item.primary_url)

    result: list[SourceItem] = []
    for item in items:
        if item.primary_url:
            result.append(item)
            continue
        matches = title_to_urls.get(_title_key(item.strategy_name), set())
        if len(matches) == 1:
            result.append(
                SourceItem(
                    path=item.path,
                    relative_path=item.relative_path,
                    encoding=item.encoding,
                    sha256=item.sha256,
                    size=item.size,
                    urls=item.urls,
                    primary_url=next(iter(matches)),
                    selection_method="matched_local_title",
                    strategy_name=item.strategy_name,
                    declared_title=item.declared_title,
                    declared_author=item.declared_author,
                )
            )
        else:
            result.append(item)
    return result


def parse_community_id(url: str) -> str | None:
    match = COMMUNITY_ID_RE.search(urllib.parse.urlsplit(url).path)
    return match.group(1) if match else None


def _payload_data(payload: dict[str, Any], url: str) -> dict[str, Any]:
    if payload.get("code") != "00000" or not isinstance(payload.get("data"), dict):
        raise FetchError(url, f"接口错误 code={payload.get('code')} msg={payload.get('msg')}")
    return payload["data"]


def sanitize_author(author: Any) -> dict[str, Any]:
    if not isinstance(author, dict):
        return {}
    keys = ("userId", "alias", "introduction", "vipType", "headImgKey")
    return {key: author.get(key) for key in keys if author.get(key) not in (None, "")}


def sanitize_post(data: dict[str, Any]) -> dict[str, Any]:
    keys = (
        "postId",
        "uniqueKey",
        "title",
        "content",
        "type",
        "status",
        "addTime",
        "modTime",
        "lastActiveTime",
        "lastPubTime",
        "backtestId",
        "backtestName",
        "replyCount",
        "viewCount",
        "collectionCount",
        "likeCount",
        "disLikeCount",
        "backtestCloneCount",
        "notebookCloneCount",
        "fileDownloadCount",
        "fileName",
        "fileType",
        "fileSize",
        "postCount",
        "followersCount",
        "followingCount",
    )
    result = {key: data.get(key) for key in keys if data.get(key) not in (None, "")}
    result["author"] = sanitize_author(data.get("author"))
    tags = data.get("tagInfo")
    if isinstance(tags, list):
        result["tags"] = [
            {"id": tag.get("tagKey") or tag.get("tagId"), "name": tag.get("name")}
            for tag in tags
            if isinstance(tag, dict)
        ]
    return result


def resolve_post(
    client: HttpClient, source_url: str
) -> tuple[str, str, dict[str, Any], list[str]]:
    request_urls: list[str] = []
    _, final_url, _ = client.get(
        source_url,
        accept="text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    )
    request_urls.append(source_url)
    community_id = parse_community_id(final_url) or parse_community_id(source_url)
    if not community_id:
        raise FetchError(source_url, f"无法从重定向地址识别帖子 ID：{final_url}")

    for _ in range(3):
        detail_url = (
            "https://www.joinquant.com/community/post/detailV2?"
            + urllib.parse.urlencode({"postId": community_id})
        )
        payload, _ = client.get_json(detail_url, referer=final_url)
        request_urls.append(detail_url)
        data = payload.get("data")
        if isinstance(data, dict) and data.get("url"):
            final_url = urllib.parse.urljoin("https://www.joinquant.com", str(data["url"]))
            next_id = parse_community_id(final_url)
            if not next_id or next_id == community_id:
                break
            community_id = next_id
            continue
        data = _payload_data(payload, detail_url)
        canonical_id = str(data.get("uniqueKey") or community_id)
        canonical_url = f"https://www.joinquant.com/view/community/detail/{canonical_id}"
        return canonical_url, canonical_id, data, request_urls
    raise FetchError(source_url, "帖子详情连续重定向，未得到正文")


def _strip_tags(value: str) -> str:
    return re.sub(r"<[^>]+>", "", html.unescape(value)).strip()


def _tag_by_id(page: str, element_id: str) -> list[dict[str, str]]:
    id_part = rf"\bid=[\"']{re.escape(element_id)}[\"']"
    paired = re.compile(
        rf"<(?P<tag>[A-Za-z0-9]+)\b(?P<attrs>[^>]*{id_part}[^>]*)>"
        rf"(?P<body>.*?)</(?P=tag)>",
        re.IGNORECASE | re.DOTALL,
    )
    single = re.compile(
        rf"<(?P<tag>input|meta)\b(?P<attrs>[^>]*{id_part}[^>]*)/?>",
        re.IGNORECASE | re.DOTALL,
    )
    values: list[dict[str, str]] = []
    for match in paired.finditer(page):
        attrs = match.group("attrs")
        value_match = re.search(r"\bvalue=[\"']([^\"']*)[\"']", attrs, re.IGNORECASE)
        values.append(
            {
                "value": html.unescape(value_match.group(1)) if value_match else "",
                "text": _strip_tags(match.group("body")),
            }
        )
    for match in single.finditer(page):
        attrs = match.group("attrs")
        value_match = re.search(r"\bvalue=[\"']([^\"']*)[\"']", attrs, re.IGNORECASE)
        values.append(
            {"value": html.unescape(value_match.group(1)) if value_match else "", "text": ""}
        )
    return values


def _first_id_value(page: str, element_id: str, prefer_text: bool = True) -> str | None:
    values = _tag_by_id(page, element_id)
    for item in values:
        candidates = (item["text"], item["value"]) if prefer_text else (item["value"], item["text"])
        for candidate in candidates:
            if candidate:
                return candidate
    return None


def _parse_number(value: str | None) -> int | float | None:
    if not value:
        return None
    cleaned = re.sub(r"[^\d.\-]", "", value.replace(",", ""))
    if not cleaned:
        return None
    number = float(cleaned)
    return int(number) if number.is_integer() else number


def parse_summary_page(page: str) -> dict[str, Any]:
    frequency_items = _tag_by_id(page, "frequency")
    frequency_code = None
    frequency_label = None
    if frequency_items:
        frequency_code = frequency_items[0]["value"] or None
        frequency_label = frequency_items[0]["text"] or None

    backtest_ids = [
        item["value"] or item["text"]
        for item in _tag_by_id(page, "backtestId")
        if item["value"] or item["text"]
    ]
    python_match = re.search(r"\bvar\s+pythonVersion\s*=\s*(\d+)", page)
    clone_count_match = re.search(
        r"""class=["'][^"']*jq-c-cloneCount[^"']*["'][^>]*>(.*?)</""",
        page,
        re.IGNORECASE | re.DOTALL,
    )
    return {
        "start_date": _first_id_value(page, "startDate"),
        "end_date": _first_id_value(page, "endDate"),
        "base_capital": _parse_number(_first_id_value(page, "baseCapital")),
        "frequency_code": frequency_code,
        "frequency_label": frequency_label,
        "backtest_type": _parse_number(
            _first_id_value(page, "backtestType", prefer_text=False)
        ),
        "page_backtest_ids": backtest_ids,
        "numeric_backtest_id": _first_id_value(
            page, "backtestId-decryptId", prefer_text=False
        ),
        "numeric_post_id": _first_id_value(page, "postId", prefer_text=False),
        "python_version": int(python_match.group(1)) if python_match else None,
        "clone_count": (
            _parse_number(_strip_tags(clone_count_match.group(1)))
            if clone_count_match
            else None
        ),
    }


def _iter_reply_nodes(value: Any) -> Iterable[dict[str, Any]]:
    if isinstance(value, dict):
        if "replyId" in value:
            yield value
        for child in value.values():
            yield from _iter_reply_nodes(child)
    elif isinstance(value, list):
        for child in value:
            yield from _iter_reply_nodes(child)


def find_reply_backtests(
    client: HttpClient,
    community_id: str,
    referer: str,
    *,
    max_pages: int,
    include_other_replies: bool = False,
) -> tuple[list[dict[str, Any]], int, list[str]]:
    """遍历帖子回复，找出附带回测的回复。

    Parameters
    ----------
    include_other_replies :
        为 True 时也返回非作者回复中的回测（location="other_reply"）。
        为 False 时只返回作者本人的回测，其他用户回测仅计数。
    """
    author_backtests: dict[str, dict[str, Any]] = {}
    other_backtest_ids: set[str] = set()
    request_urls: list[str] = []
    page = 1
    total_count = 0
    while page <= max_pages:
        url = "https://www.joinquant.com/community/post/replyList?" + urllib.parse.urlencode(
            {"page": page, "postId": community_id}
        )
        payload, _ = client.get_json(url, referer=referer)
        request_urls.append(url)
        data = _payload_data(payload, url)
        total_count = int(data.get("totalCount") or total_count or 0)
        nodes = list(_iter_reply_nodes(data.get("replyArr", [])))
        nodes.extend(_iter_reply_nodes(data.get("bountyReply", [])))
        for node in nodes:
            backtest_id = str(node.get("backtestId") or "")
            if not backtest_id:
                continue
            if node.get("isPostUser") or node.get("isOwner"):
                author_backtests.setdefault(
                    backtest_id,
                    {
                        "backtest_id": backtest_id,
                        "backtest_name": node.get("backtestName") or "",
                        "reply_id": node.get("replyId") or "",
                        "add_time": node.get("addTime") or "",
                        "location": "author_reply",
                    },
                )
            elif include_other_replies:
                author_backtests.setdefault(
                    backtest_id,
                    {
                        "backtest_id": backtest_id,
                        "backtest_name": node.get("backtestName") or "",
                        "reply_id": node.get("replyId") or "",
                        "add_time": node.get("addTime") or "",
                        "location": "other_reply",
                    },
                )
            else:
                other_backtest_ids.add(backtest_id)
        if page * 20 >= total_count or not data.get("replyArr"):
            break
        page += 1
    selected = sorted(
        author_backtests.values(), key=lambda item: (item.get("add_time", ""), item["backtest_id"])
    )
    other_count = 0 if include_other_replies else len(other_backtest_ids)
    return selected, other_count, request_urls


def fetch_curve(
    client: HttpClient,
    backtest_id: str,
    referer: str,
    *,
    max_pages: int = 20,
) -> tuple[dict[str, Any], list[str]]:
    strategy_time: list[Any] = []
    strategy_value: list[Any] = []
    benchmark_time: list[Any] = []
    benchmark_value: list[Any] = []
    request_urls: list[str] = []
    offset = 0
    user_offset = 0
    state: Any = None
    for _ in range(max_pages):
        url = "https://www.joinquant.com/algorithm/backtest/result?" + urllib.parse.urlencode(
            {
                "backtestId": backtest_id,
                "offset": offset,
                "userRecordOffset": user_offset,
            }
        )
        payload, _ = client.get_json(url, referer=referer)
        request_urls.append(url)
        data = _payload_data(payload, url)
        state = data.get("state")
        result = data.get("result") if isinstance(data.get("result"), dict) else {}
        count = int(result.get("count") or 0)
        if count <= 0:
            break
        overall = result.get("overallReturn") or {}
        benchmark = result.get("benchmark") or {}
        strategy_time.extend(overall.get("time") or [])
        strategy_value.extend(overall.get("value") or [])
        benchmark_time.extend(benchmark.get("time") or [])
        benchmark_value.extend(benchmark.get("value") or [])
        offset = int(result.get("offset") or offset) + count
    return (
        {
            "state": state,
            "strategy": {"time": strategy_time, "value": strategy_value},
            "benchmark": {"time": benchmark_time, "value": benchmark_value},
            "point_count": len(strategy_time),
        },
        request_urls,
    )


def display_metrics(stats: dict[str, Any]) -> dict[str, Any]:
    percent_fields = (
        "algorithm_return",
        "benchmark_return",
        "annual_algo_return",
        "annual_bm_return",
        "max_drawdown",
        "algorithm_volatility",
        "benchmark_volatility",
        "win_ratio",
        "day_win_ratio",
        "avg_trade_return",
        "turnover_rate",
    )
    result: dict[str, Any] = {}
    for key in percent_fields:
        value = stats.get(key)
        if isinstance(value, (int, float)):
            result[f"{key}_percent"] = round(value * 100, 6)
    for key in (
        "sharpe",
        "sortino",
        "information",
        "alpha",
        "beta",
        "profit_loss_ratio",
        "avg_position_days",
        "trading_days",
        "win_count",
        "lose_count",
        "max_drawdown_period",
        "excess_return_max_drawdown_period",
    ):
        if key in stats:
            result[key] = stats[key]
    return result


def fetch_backtest(
    client: HttpClient,
    *,
    backtest_id: str,
    backtest_name: str,
    community_id: str,
    canonical_url: str,
    reply_id: str = "",
    location: str = "post",
    add_time: str = "",
    include_series: bool,
) -> tuple[dict[str, Any], list[str]]:
    query = urllib.parse.urlencode(
        {
            "backtestId": backtest_id,
            "postId": community_id,
            "replyId": reply_id,
            "iframe": 1,
        }
    )
    summary_url = f"https://www.joinquant.com/algorithm/backtest/summary?{query}"
    body, _, _ = client.get(
        summary_url,
        referer=canonical_url,
        accept="text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    )
    page = body.decode("utf-8-sig", errors="replace")
    configuration = parse_summary_page(page)

    stats_url = "https://www.joinquant.com/algorithm/backtest/stats?" + urllib.parse.urlencode(
        {"backtestId": backtest_id}
    )
    stats_payload, _ = client.get_json(stats_url, referer=summary_url)
    stats = _payload_data(stats_payload, stats_url)
    request_urls = [summary_url, stats_url]
    result: dict[str, Any] = {
        "backtest_id": backtest_id,
        "backtest_name": backtest_name,
        "location": location,
        "reply_id": reply_id or None,
        "reply_add_time": add_time or None,
        "summary_url": summary_url,
        "configuration": configuration,
        "stats": stats,
        "display_metrics": display_metrics(stats),
    }
    if include_series:
        curve, curve_urls = fetch_curve(client, backtest_id, summary_url)
        result["return_series"] = curve
        request_urls.extend(curve_urls)
    return result, request_urls


def fetch_remote(
    client: HttpClient,
    source_url: str,
    *,
    include_series: bool,
    max_reply_pages: int,
    include_other_replies: bool = False,
) -> dict[str, Any]:
    collected_at = utc_now()
    try:
        canonical_url, community_id, post_data, request_urls = resolve_post(client, source_url)
        post = sanitize_post(post_data)
        candidates: list[dict[str, Any]] = []
        other_reply_backtests = 0
        if post_data.get("backtestId"):
            candidates.append(
                {
                    "backtest_id": str(post_data["backtestId"]),
                    "backtest_name": str(post_data.get("backtestName") or ""),
                    "reply_id": "",
                    "add_time": "",
                    "location": "post",
                }
            )
        else:
            candidates, other_reply_backtests, reply_urls = find_reply_backtests(
                client,
                community_id,
                canonical_url,
                max_pages=max_reply_pages,
                include_other_replies=include_other_replies,
            )
            request_urls.extend(reply_urls)

        backtests: list[dict[str, Any]] = []
        backtest_errors: list[dict[str, Any]] = []
        for candidate in candidates:
            try:
                backtest, backtest_urls = fetch_backtest(
                    client,
                    backtest_id=candidate["backtest_id"],
                    backtest_name=candidate["backtest_name"],
                    community_id=community_id,
                    canonical_url=canonical_url,
                    reply_id=candidate["reply_id"],
                    location=candidate["location"],
                    add_time=candidate["add_time"],
                    include_series=include_series,
                )
                backtests.append(backtest)
                request_urls.extend(backtest_urls)
            except FetchError as exc:
                backtest_errors.append(
                    {
                        "backtest_id": candidate["backtest_id"],
                        "message": str(exc),
                        "url": exc.url,
                        "http_status": exc.status,
                    }
                )

        if backtests:
            status = "ok"
        elif candidates and backtest_errors:
            status = "backtest_fetch_error"
        else:
            status = "post_without_backtest"
        return {
            "status": status,
            "collected_at": collected_at,
            "requested_url": source_url,
            "canonical_url": canonical_url,
            "community_id": community_id,
            "post": post,
            "backtests": backtests,
            "backtest_errors": backtest_errors,
            "other_user_reply_backtest_count": other_reply_backtests,
            "request_urls": request_urls,
        }
    except FetchError as exc:
        return {
            "status": "error",
            "collected_at": collected_at,
            "requested_url": source_url,
            "error": {
                "message": str(exc),
                "url": exc.url,
                "http_status": exc.status,
            },
        }
    except Exception as exc:  # 保留单条异常，避免中断整个长任务
        return {
            "status": "error",
            "collected_at": collected_at,
            "requested_url": source_url,
            "error": {"message": f"{type(exc).__name__}: {exc}"},
        }


def item_output_path(output_root: Path, item: SourceItem) -> Path:
    return output_root / item.relative_path.with_suffix(".json")


def make_record(source_root: Path, item: SourceItem, remote: dict[str, Any] | None) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "local": {
            "source_root": str(source_root),
            "relative_path": item.relative_path.as_posix(),
            "category": item.relative_path.parts[0] if len(item.relative_path.parts) > 1 else "",
            "file_name": item.path.name,
            "strategy_name": item.strategy_name,
            "declared_title": item.declared_title,
            "declared_author": item.declared_author,
            "extension": item.path.suffix.lower(),
            "encoding": item.encoding,
            "size": item.size,
            "sha256": item.sha256,
            "joinquant_urls": list(item.urls),
            "primary_url": item.primary_url,
            "url_selection_method": item.selection_method,
        },
        "remote": remote,
    }


def atomic_write_json(path: Path, payload: Any, *, indent: int | None = 2) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_suffix(path.suffix + ".part")
    temp_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=indent) + ("\n" if indent else ""),
        encoding="utf-8",
    )
    os.replace(temp_path, path)


def atomic_write_text(path: Path, text: str) -> None:
    if path.exists() and path.read_text(encoding="utf-8") == text:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_suffix(path.suffix + ".part")
    temp_path.write_text(text, encoding="utf-8", newline="\n")
    os.replace(temp_path, path)


def redact_archived_source(text: str) -> tuple[str, int]:
    redacted_count = 0

    def replace_email(match: re.Match[str]) -> str:
        nonlocal redacted_count
        redacted_count += 1
        return "<redacted-email>"

    def replace_secret(match: re.Match[str]) -> str:
        nonlocal redacted_count
        redacted_count += 1
        return (
            f"{match.group('prefix')}{match.group('quote')}"
            f"<redacted-secret>{match.group('quote')}"
        )

    redacted = EMAIL_ADDRESS_RE.sub(replace_email, text)
    redacted = SECRET_ASSIGNMENT_RE.sub(replace_secret, redacted)
    return redacted, redacted_count


def prepare_archived_source(text: str) -> tuple[str, list[str], int]:
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    transformations = ["transcode_utf8"]
    lines = normalized.splitlines(keepends=True)
    marker = next(
        (
            index
            for index, line in enumerate(lines)
            if line.strip() == "原文策略源码如下："
        ),
        None,
    )
    if (
        lines
        and lines[0].strip().startswith("该策略由聚宽用户分享")
        and marker is not None
    ):
        lines[: marker + 1] = [
            "# " + line if line.strip() else "#\n"
            for line in lines[: marker + 1]
        ]
        normalized = "".join(lines)
        transformations.append("comment_vendor_preamble")
    normalized, redacted_count = redact_archived_source(normalized)
    if redacted_count:
        transformations.append("redact_credentials")
    if normalized and not normalized.endswith("\n"):
        normalized += "\n"
    return normalized, transformations, redacted_count


def python3_parse_result(text: str) -> tuple[bool, dict[str, Any] | None]:
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", SyntaxWarning)
            ast.parse(text)
    except SyntaxError as exc:
        return False, {
            "line": exc.lineno,
            "offset": exc.offset,
            "message": exc.msg,
        }
    return True, None


def archive_source_items(items: list[SourceItem], archive_root: Path) -> dict[str, int]:
    manifest: list[dict[str, Any]] = []
    parse_ok_count = 0
    for item in items:
        text, _, _ = decode_source(item.path)
        archived_text, transformations, redacted_count = prepare_archived_source(text)
        parse_ok, parse_error = python3_parse_result(archived_text)
        parse_ok_count += int(parse_ok)
        archive_path = item.relative_path.with_suffix(".py")
        atomic_write_text(archive_root / archive_path, archived_text)
        manifest.append(
            {
                "archive_path": archive_path.as_posix(),
                "strategy_name": item.strategy_name,
                "source_extension": item.path.suffix.lower(),
                "source_encoding": item.encoding,
                "source_size": item.size,
                "source_sha256": item.sha256,
                "archive_sha256": hashlib.sha256(
                    archived_text.encode("utf-8")
                ).hexdigest(),
                "transformations": transformations,
                "redacted_value_count": redacted_count,
                "python3_ast_parse": parse_ok,
                "python3_ast_error": parse_error,
                "primary_url": item.primary_url,
            }
        )
    manifest_text = "".join(
        json.dumps(row, ensure_ascii=False) + "\n" for row in manifest
    )
    atomic_write_text(archive_root / "manifest.jsonl", manifest_text)
    return {
        "item_count": len(items),
        "python3_ast_parse_ok": parse_ok_count,
        "python3_ast_parse_failed": len(items) - parse_ok_count,
    }


def load_cached_remote(
    output_root: Path,
    items: list[SourceItem],
    *,
    require_series: bool,
) -> dict[str, Any] | None:
    for item in items:
        path = item_output_path(output_root, item)
        if not path.exists():
            continue
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        remote = record.get("remote")
        cached_backtests = remote.get("backtests", []) if isinstance(remote, dict) else []
        has_required_series = not require_series or all(
            "return_series" in backtest for backtest in cached_backtests
        )
        if (
            record.get("schema_version") == SCHEMA_VERSION
            and isinstance(remote, dict)
            and remote.get("status") in SUCCESS_STATUSES
            and has_required_series
        ):
            return remote
    return None


def _percent(stats: dict[str, Any], key: str) -> float | None:
    value = stats.get(key)
    return round(value * 100, 6) if isinstance(value, (int, float)) else None


def summary_row(record: dict[str, Any]) -> dict[str, Any]:
    local = record["local"]
    remote = record.get("remote") or {}
    post = remote.get("post") or {}
    author = post.get("author") or {}
    backtests = remote.get("backtests") or []
    backtest = backtests[0] if backtests else {}
    config = backtest.get("configuration") or {}
    stats = backtest.get("stats") or {}
    return {
        "local_category": local.get("category"),
        "local_file": local.get("relative_path"),
        "local_strategy_name": local.get("strategy_name"),
        "local_declared_title": local.get("declared_title"),
        "local_declared_author": local.get("declared_author"),
        "primary_url": local.get("primary_url"),
        "canonical_url": remote.get("canonical_url"),
        "status": remote.get("status") or "no_source_url",
        "post_title": post.get("title"),
        "author": author.get("alias"),
        "post_time": post.get("addTime"),
        "backtest_count": len(backtests),
        "backtest_name": backtest.get("backtest_name"),
        "backtest_location": backtest.get("location"),
        "start_date": config.get("start_date"),
        "end_date": config.get("end_date"),
        "base_capital": config.get("base_capital"),
        "frequency_code": config.get("frequency_code"),
        "frequency_label": config.get("frequency_label"),
        "python_version": config.get("python_version"),
        "strategy_return_percent": _percent(stats, "algorithm_return"),
        "benchmark_return_percent": _percent(stats, "benchmark_return"),
        "annual_return_percent": _percent(stats, "annual_algo_return"),
        "benchmark_annual_return_percent": _percent(stats, "annual_bm_return"),
        "alpha": stats.get("alpha"),
        "beta": stats.get("beta"),
        "sharpe": stats.get("sharpe"),
        "sortino": stats.get("sortino"),
        "information_ratio": stats.get("information"),
        "max_drawdown_percent": _percent(stats, "max_drawdown"),
        "max_drawdown_period": json.dumps(
            stats.get("max_drawdown_period"), ensure_ascii=False
        )
        if stats.get("max_drawdown_period")
        else None,
        "win_ratio_percent": _percent(stats, "win_ratio"),
        "day_win_ratio_percent": _percent(stats, "day_win_ratio"),
        "profit_loss_ratio": stats.get("profit_loss_ratio"),
        "win_count": stats.get("win_count"),
        "lose_count": stats.get("lose_count"),
        "avg_trade_return_percent": _percent(stats, "avg_trade_return"),
        "avg_position_days": stats.get("avg_position_days"),
        "turnover_rate_percent": _percent(stats, "turnover_rate"),
        "trading_days": stats.get("trading_days"),
        "view_count": post.get("viewCount"),
        "reply_count": post.get("replyCount"),
        "like_count": post.get("likeCount"),
        "collection_count": post.get("collectionCount"),
        "backtest_clone_count": post.get("backtestCloneCount"),
        "error": (remote.get("error") or {}).get("message"),
    }


def write_summaries(output_root: Path, records: list[dict[str, Any]]) -> dict[str, Any]:
    rows = [summary_row(record) for record in records]
    output_root.mkdir(parents=True, exist_ok=True)
    csv_path = output_root / "summary.csv"
    with csv_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()) if rows else [])
        if rows:
            writer.writeheader()
            writer.writerows(rows)

    jsonl_path = output_root / "summary.jsonl"
    with jsonl_path.open("w", encoding="utf-8", newline="\n") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")

    issues = [
        row
        for row in rows
        if row["status"] not in {"ok"}
        or not row["primary_url"]
        or not row["backtest_count"]
    ]
    issues_path = output_root / "issues.jsonl"
    with issues_path.open("w", encoding="utf-8", newline="\n") as handle:
        for row in issues:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")

    status_counts: dict[str, int] = {}
    for row in rows:
        status_counts[row["status"]] = status_counts.get(row["status"], 0) + 1
    run_summary = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": utc_now(),
        "item_count": len(rows),
        "status_counts": status_counts,
        "with_source_url": sum(bool(row["primary_url"]) for row in rows),
        "with_backtest": sum(bool(row["backtest_count"]) for row in rows),
        "issue_count": len(issues),
        "files": {
            "summary_csv": csv_path.name,
            "summary_jsonl": jsonl_path.name,
            "issues_jsonl": issues_path.name,
        },
    }
    atomic_write_json(output_root / "run-summary.json", run_summary)
    return run_summary


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, default=DEFAULT_SOURCE_ROOT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument(
        "--source-archive",
        type=Path,
        default=DEFAULT_SOURCE_ARCHIVE_ROOT,
        help="UTF-8 .py 来源快照目录，默认 joinquant_archive/sources",
    )
    parser.add_argument(
        "--skip-source-archive",
        action="store_true",
        help="不更新仓库内的 UTF-8 .py 来源快照",
    )
    parser.add_argument(
        "--extensions",
        default=".txt,.py",
        help="逗号分隔的本地源码扩展名，默认 .txt,.py",
    )
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument(
        "--min-interval",
        type=float,
        default=0.20,
        help="所有线程相邻请求的最小间隔秒数，默认 0.20（约 5 请求/秒）",
    )
    parser.add_argument("--timeout", type=float, default=30.0)
    parser.add_argument("--retries", type=int, default=3)
    parser.add_argument("--max-reply-pages", type=int, default=20)
    parser.add_argument("--include-series", action="store_true", help="保存完整逐点收益曲线")
    parser.add_argument("--include-other-replies", action="store_true", help="同时抓取非作者回复中的回测数据")
    parser.add_argument("--refresh", action="store_true", help="忽略已有成功 JSON，重新抓取")
    parser.add_argument("--limit", type=int, help="只处理前 N 个文件，便于试跑")
    return parser.parse_args(argv)


def run(args: argparse.Namespace) -> dict[str, Any]:
    source_root = args.source_root.resolve()
    output_root = args.output.resolve()
    if not source_root.is_dir():
        raise SystemExit(f"源目录不存在：{source_root}")
    extensions = {
        value.strip().lower()
        if value.strip().startswith(".")
        else "." + value.strip().lower()
        for value in args.extensions.split(",")
        if value.strip()
    }
    all_items = inventory_source_files(source_root, extensions)
    if not args.skip_source_archive:
        archive_summary = archive_source_items(all_items, args.source_archive.resolve())
        print(
            f"归档 {archive_summary['item_count']} 个 UTF-8 .py 来源快照，"
            f"{archive_summary['python3_ast_parse_ok']} 个通过 Python 3 AST 解析，"
            f"{archive_summary['python3_ast_parse_failed']} 个保留原始语法问题。"
        )
    items = all_items
    if args.limit is not None:
        items = items[: max(0, args.limit)]
    print(
        f"发现 {len(items)} 个源码文件，"
        f"{sum(bool(item.primary_url) for item in items)} 个可定位聚宽原帖。"
    )

    groups: dict[str, list[SourceItem]] = {}
    for item in items:
        if item.primary_url:
            groups.setdefault(item.primary_url, []).append(item)

    remote_by_url: dict[str, dict[str, Any]] = {}
    to_fetch: list[str] = []
    for source_url, group_items in groups.items():
        cached = (
            None
            if args.refresh
            else load_cached_remote(
                output_root,
                group_items,
                require_series=args.include_series,
            )
        )
        if cached is not None:
            remote_by_url[source_url] = cached
        else:
            to_fetch.append(source_url)
    print(f"复用 {len(remote_by_url)} 个已有结果，本次抓取 {len(to_fetch)} 个唯一原帖。")

    client = HttpClient(
        timeout=args.timeout,
        retries=args.retries,
        min_interval=args.min_interval,
    )
    if to_fetch:
        with ThreadPoolExecutor(max_workers=max(1, args.workers)) as executor:
            future_to_url = {
                executor.submit(
                    fetch_remote,
                    client,
                    source_url,
                    include_series=args.include_series,
                    max_reply_pages=args.max_reply_pages,
                    include_other_replies=args.include_other_replies,
                ): source_url
                for source_url in to_fetch
            }
            completed = 0
            for future in as_completed(future_to_url):
                source_url = future_to_url[future]
                remote = future.result()
                remote_by_url[source_url] = remote
                completed += 1
                print(
                    f"[{completed}/{len(to_fetch)}] "
                    f"{remote.get('status', 'error'):>22} {source_url}",
                    flush=True,
                )
                for item in groups[source_url]:
                    atomic_write_json(
                        item_output_path(output_root, item),
                        make_record(source_root, item, remote),
                    )

    records: list[dict[str, Any]] = []
    for item in items:
        remote = remote_by_url.get(item.primary_url) if item.primary_url else None
        record = make_record(source_root, item, remote)
        atomic_write_json(item_output_path(output_root, item), record)
        records.append(record)

    run_summary = write_summaries(output_root, records)
    print(json.dumps(run_summary, ensure_ascii=False, indent=2))
    return run_summary


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    run(args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
