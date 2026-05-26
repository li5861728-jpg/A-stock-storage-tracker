"""新闻聚合 - 从多源拉取并过滤存储板块相关新闻"""

from __future__ import annotations

import logging
import pandas as pd
from datetime import datetime
from typing import Optional

from config import NEWS_KEYWORDS, NEWS_CACHE_PATTERN, MAX_NEWS_DISPLAY
from src.utils import now_cst, today_str, news_hash, load_json, save_json

logger = logging.getLogger(__name__)


def _match_keywords(text: str) -> bool:
    """判断文本是否匹配存储板块关键词"""
    if not text:
        return False
    text_lower = text.lower()
    return any(
        kw.lower() in text_lower
        for kw in NEWS_KEYWORDS
    )


def _normalize_news_item(item: dict) -> dict | None:
    """标准化单条新闻格式"""
    title = (item.get("title") or item.get("标题") or "").strip()
    content = (item.get("content") or item.get("内容") or "").strip()
    source = (item.get("source") or item.get("来源") or "未知来源").strip()
    pub_time = item.get("pub_time") or item.get("发布时间") or now_cst().strftime("%Y-%m-%d %H:%M")

    if not title:
        return None
    if not _match_keywords(title + content):
        return None

    return {
        "hash": news_hash(title),
        "title": title,
        "content": content[:300] if content else "",
        "source": source,
        "pub_time": str(pub_time),
        "fetch_time": now_cst().isoformat(),
    }


def _fetch_cls_news() -> list[dict]:
    """从财联社获取全球财经新闻"""
    try:
        import akshare as ak
        df = ak.stock_info_global_cls()
        if df is None or df.empty:
            return []
        items = []
        for _, row in df.iterrows():
            item = _normalize_news_item({
                "title": row.get("标题", ""),
                "content": row.get("内容", ""),
                "source": "财联社",
                "pub_time": row.get("发布时间", ""),
            })
            if item:
                items.append(item)
        return items
    except Exception as e:
        logger.warning(f"财联社新闻获取失败: {e}")
        return []


def _fetch_em_news() -> list[dict]:
    """从东方财富获取全球财经新闻"""
    try:
        import akshare as ak
        df = ak.stock_info_global_em()
        if df is None or df.empty:
            return []
        items = []
        for _, row in df.iterrows():
            item = _normalize_news_item({
                "title": row.get("标题", ""),
                "content": row.get("内容", ""),
                "source": "东方财富",
                "pub_time": row.get("发布时间", ""),
            })
            if item:
                items.append(item)
        return items
    except Exception as e:
        logger.warning(f"东方财富新闻获取失败: {e}")
        return []


def _fetch_sina_news() -> list[dict]:
    """从新浪获取全球财经新闻"""
    try:
        import akshare as ak
        df = ak.stock_info_global_sina()
        if df is None or df.empty:
            return []
        items = []
        for _, row in df.iterrows():
            item = _normalize_news_item({
                "title": row.get("标题", ""),
                "content": row.get("内容", ""),
                "source": "新浪财经",
                "pub_time": row.get("发布时间", ""),
            })
            if item:
                items.append(item)
        return items
    except Exception as e:
        logger.warning(f"新浪新闻获取失败: {e}")
        return []


def _dedup_news(items: list[dict]) -> list[dict]:
    """按标题哈希去重，保留发布时间最早的"""
    seen: dict[str, dict] = {}
    for item in items:
        h = item["hash"]
        if h not in seen:
            seen[h] = item
        else:
            # 保留内容更丰富的
            if len(item.get("content", "")) > len(seen[h].get("content", "")):
                seen[h] = item
    return list(seen.values())


def _load_cached_news(date_str: str) -> list[dict]:
    """加载当日已缓存的新闻"""
    path = NEWS_CACHE_PATTERN.format(date=date_str)
    data = load_json(path)
    if isinstance(data, list):
        return data
    return []


def _save_news_cache(date_str: str, items: list[dict]) -> None:
    """保存新闻缓存"""
    path = NEWS_CACHE_PATTERN.format(date=date_str)
    save_json(path, items)


def fetch_news(force_refresh: bool = False) -> list[dict]:
    """
    获取存储板块相关新闻
    返回按发布时间倒序排列的新闻列表
    """
    today = today_str()

    # 加载已有缓存
    cached = _load_cached_news(today)
    cached_hashes = {item["hash"] for item in cached} if cached else set()

    if not force_refresh and cached:
        return cached[:MAX_NEWS_DISPLAY]

    # 从各源拉取新新闻
    all_new = []
    all_new += _fetch_cls_news()
    all_new += _fetch_em_news()
    all_new += _fetch_sina_news()

    if not all_new:
        logger.warning("No news fetched from any source, using cache")
        return cached[:MAX_NEWS_DISPLAY] if cached else []

    # 去重
    new_items = _dedup_news(all_new)

    # 合并新老新闻
    if cached:
        for item in new_items:
            if item["hash"] not in cached_hashes:
                cached.append(item)
    else:
        cached = new_items

    # 按发布时间排序（最新的在前）
    cached.sort(key=lambda x: str(x.get("pub_time", "")), reverse=True)

    # 保存
    _save_news_cache(today, cached)

    return cached[:MAX_NEWS_DISPLAY]


def get_new_uncached_news(news_items: list[dict]) -> list[dict]:
    """筛选出尚未进行情绪分析的新闻"""
    from config import SENTIMENT_CACHE_PATTERN
    date_str = today_str()
    path = SENTIMENT_CACHE_PATTERN.format(date=date_str)
    sentiment_cache = load_json(path) or {}

    uncached = []
    for item in news_items:
        h = item["hash"]
        if h not in sentiment_cache:
            uncached.append(item)
    return uncached
