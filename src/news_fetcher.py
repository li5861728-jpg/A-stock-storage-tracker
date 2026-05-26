"""新闻聚合 - 直接 HTTP 请求拉取多平台新闻"""

from __future__ import annotations

import logging
import requests
import re
import json
from datetime import datetime

from config import NEWS_KEYWORDS, NEWS_CACHE_PATTERN, MAX_NEWS_DISPLAY
from src.utils import now_cst, today_str, news_hash, load_json, save_json

logger = logging.getLogger(__name__)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "zh-CN,zh;q=0.9",
}


def _match_keywords(text: str) -> bool:
    if not text:
        return False
    low = text.lower()
    return any(kw.lower() in low for kw in NEWS_KEYWORDS)


def _clean_html(text: str) -> str:
    if not text:
        return ""
    return re.sub(r"<[^>]+>", "", text).strip()


def _normalize(title: str, content: str = "", source: str = "", pub_time: str = "") -> dict | None:
    title = _clean_html(title).strip()
    content = _clean_html(content).strip()
    if not title or len(title) < 4:
        return None
    if not _match_keywords(title + content):
        return None
    return {
        "hash": news_hash(title),
        "title": title,
        "content": content[:400] if content else "",
        "source": source or "公开资讯",
        "pub_time": str(pub_time) or now_cst().strftime("%Y-%m-%d %H:%M"),
        "fetch_time": now_cst().isoformat(),
    }


def _ts_to_str(ts) -> str:
    """时间戳转字符串"""
    try:
        ts = int(ts)
        if ts > 1e12:  # 毫秒
            ts = ts / 1000
        return datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M")
    except Exception:
        return str(ts)


# ============================================================
# 源 1: 新浪财经 (works globally)
# ============================================================
def _fetch_sina() -> list[dict]:
    items = []
    for page in [1, 2, 3]:
        try:
            url = f"https://feed.mix.sina.com.cn/api/roll/get?pageid=153&lid=2516&k=&num=50&page={page}"
            resp = requests.get(url, headers=HEADERS, timeout=15)
            data = resp.json()
            for d in data.get("result", {}).get("data", []):
                title = d.get("title", "")
                content = d.get("intro", "") or d.get("summary", "")
                item = _normalize(title, content, "新浪财经", _ts_to_str(d.get("ctime", "")))
                if item:
                    items.append(item)
        except Exception:
            break
        if len(items) >= 20:
            break
    logger.info(f"新浪: {len(items)} 条")
    return items


# ============================================================
# 源 2: 同花顺 (works globally)
# ============================================================
def _fetch_10jqka() -> list[dict]:
    items = []
    for page in [1, 2]:
        try:
            url = f"https://news.10jqka.com.cn/tapp/news/push/stock/?page={page}&tagid=&limit=30"
            resp = requests.get(url, headers=HEADERS, timeout=15)
            data = resp.json()
            for d in data.get("data", {}).get("list", []):
                title = d.get("title", "")
                content = d.get("digest", "") or d.get("summary", "")
                item = _normalize(title, content, "同花顺", _ts_to_str(d.get("ctime", "") or d.get("pub_time", "")))
                if item:
                    items.append(item)
        except Exception:
            break
    logger.info(f"同花顺: {len(items)} 条")
    return items


# ============================================================
# 源 3: 华尔街见闻 (global)
# ============================================================
def _fetch_wallstreetcn() -> list[dict]:
    items = []
    try:
        url = "https://api-one.wallstcn.com/apiv1/content/lives?channel=global-channel&client=pc&limit=40&first_page=true"
        resp = requests.get(url, headers=HEADERS, timeout=15)
        data = resp.json()
        for d in data.get("data", {}).get("items", []):
            title = d.get("title", "") or d.get("content_text", "")
            content = d.get("content_text", "") or d.get("content", "")
            if len(content) > 500:
                content = content[:500]
            item = _normalize(title, content, "华尔街见闻", _ts_to_str(d.get("display_time", "")))
            if item:
                items.append(item)
        logger.info(f"华尔街见闻: {len(items)} 条")
    except Exception as e:
        logger.warning(f"华尔街见闻失败: {e}")
    return items


# ============================================================
# 源 4: 财联社 (尝试多个接口)
# ============================================================
def _fetch_cls() -> list[dict]:
    items = []
    try:
        # 电报接口
        hdrs = {**HEADERS, "Referer": "https://www.cls.cn/telegraph"}
        url = "https://www.cls.cn/v3/depth/telegraph/list?app=CailianpressWeb&os=web&sv=8.4.6&type=telegram&page=1&rn=40"
        resp = requests.get(url, headers=hdrs, timeout=15)
        data = resp.json()
        for d in data.get("data", {}).get("roll_data", []):
            title = d.get("title", "") or d.get("content", "")
            content = d.get("content", "") or d.get("brief", "")
            if len(content) > 500:
                content = content[:500]
            item = _normalize(title, content, "财联社", _ts_to_str(d.get("ctime", "")))
            if item:
                items.append(item)
        logger.info(f"财联社: {len(items)} 条")
    except Exception as e:
        logger.warning(f"财联社失败: {e}")
    return items


# ============================================================
# 源 5: 36氪 (科技新闻, global)
# ============================================================
def _fetch_36kr() -> list[dict]:
    items = []
    try:
        url = "https://gateway.36kr.com/api/mis/nav/newsflash/flow?b_id=&per_page=30"
        resp = requests.get(url, headers=HEADERS, timeout=15)
        data = resp.json()
        for d in data.get("data", {}).get("itemList", []):
            material = d.get("templateMaterial", {})
            title = material.get("title", "") or d.get("title", "")
            content = material.get("content", "") or d.get("description", "")
            item = _normalize(title, content, "36氪", _ts_to_str(d.get("publishTime", "") or d.get("published_at", "")))
            if item:
                items.append(item)
        logger.info(f"36氪: {len(items)} 条")
    except Exception as e:
        logger.warning(f"36氪失败: {e}")
    return items


# ============================================================
# 源 6: 证券时报 (alternative endpoint)
# ============================================================
def _fetch_stcn() -> list[dict]:
    items = []
    try:
        url = "https://www.stcn.com/article/list.html?type=0&page=1&limit=30"
        resp = requests.get(url, headers={**HEADERS, "Referer": "https://www.stcn.com/"}, timeout=15)
        data = resp.json() if resp.text.strip().startswith("[") or resp.text.strip().startswith("{") else {}
        records = []
        if isinstance(data, list):
            records = data
        elif isinstance(data, dict):
            records = data.get("data", {}).get("list", []) or data.get("data", [])
            if isinstance(records, dict):
                records = list(records.values())
        for d in records:
            if not isinstance(d, dict):
                continue
            title = d.get("title", "")
            content = d.get("intro", "") or d.get("summary", "") or d.get("content", "")
            item = _normalize(title, content, "证券时报", d.get("date", "") or d.get("pub_time", ""))
            if item:
                items.append(item)
        logger.info(f"证券时报: {len(items)} 条")
    except Exception as e:
        logger.warning(f"证券时报失败: {e}")
    return items


# ============================================================
# 去重 & 缓存
# ============================================================
def _dedup(items: list[dict]) -> list[dict]:
    seen: dict[str, dict] = {}
    for item in items:
        h = item["hash"]
        if h not in seen or len(item.get("content", "")) > len(seen[h].get("content", "")):
            seen[h] = item
    return list(seen.values())


def _load_cache(date_str: str) -> list[dict]:
    data = load_json(NEWS_CACHE_PATTERN.format(date=date_str))
    return data if isinstance(data, list) else []


def _save_cache(date_str: str, items: list[dict]) -> None:
    save_json(NEWS_CACHE_PATTERN.format(date=date_str), items)


# ============================================================
# 主入口
# ============================================================
def fetch_news(force_refresh: bool = False) -> list[dict]:
    today = today_str()
    cached = _load_cache(today)

    if not force_refresh and cached:
        return cached[:MAX_NEWS_DISPLAY]

    all_new = []
    fetchers = [_fetch_sina, _fetch_10jqka, _fetch_wallstreetcn, _fetch_cls, _fetch_36kr, _fetch_stcn]
    for fetcher in fetchers:
        try:
            all_new.extend(fetcher())
        except Exception as e:
            logger.warning(f"{fetcher.__name__} 失败: {e}")

    if not all_new:
        logger.warning("所有源均失败，使用缓存")
        return cached[:MAX_NEWS_DISPLAY] if cached else []

    new_items = _dedup(all_new)
    cached_hashes = {item["hash"] for item in cached}

    if cached:
        for item in new_items:
            if item["hash"] not in cached_hashes:
                cached.append(item)
    else:
        cached = new_items

    cached.sort(key=lambda x: str(x.get("pub_time", "")), reverse=True)
    _save_cache(today, cached)
    logger.info(f"总计: {len(cached)} 条新闻")

    return cached[:MAX_NEWS_DISPLAY]


def get_new_uncached_news(news_items: list[dict]) -> list[dict]:
    from config import SENTIMENT_CACHE_PATTERN
    path = SENTIMENT_CACHE_PATTERN.format(date=today_str())
    sentiment_cache = load_json(path) or {}
    return [item for item in news_items if item["hash"] not in sentiment_cache]
