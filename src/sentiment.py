"""情绪分析 - 使用 DeepSeek API 判断新闻对存储板块的利好/利空程度"""

from __future__ import annotations

import json
import logging
import requests
from typing import Optional

from config import (
    DEEPSEEK_API_KEY,
    DEEPSEEK_MODEL,
    DEEPSEEK_BASE_URL,
    SENTIMENT_CACHE_PATTERN,
    SENTIMENT_BATCH_SIZE,
)
from src.utils import today_str, load_json, save_json

logger = logging.getLogger(__name__)


SYSTEM_PROMPT = """你是一位专业的A股存储半导体板块分析师。你擅长解读财经新闻对存储板块（涵盖存储芯片设计、模组、设备、材料、封测等全产业链）的影响。

请分析以下新闻，判断该新闻对A股存储板块的整体影响。A股存储板块代表公司包括：兆易创新(603986)、江波龙(301308)、佰维存储(688525)、北京君正(300223)、澜起科技(688008)、深科技(000021)、北方华创(002371)、中微公司(688012)、中芯国际(688981)等。

输出严格按以下JSON格式，不要任何其他文字：
{
  "sentiment": "bullish" | "bearish" | "neutral",
  "bullish_percentage": <整数0-100>,
  "bearish_percentage": <整数0-100>,
  "confidence": <整数0-100>,
  "affected_stocks": ["<代码1>", "<代码2>"],
  "reasoning": "<一句话理由，中文，不超50字>"
}

规则：
1. bullish_percentage + bearish_percentage = 100
2. 明显利好（如涨价、政策扶持、技术突破、订单增加）→ bullish_percentage >= 60
3. 明显利空（如制裁升级、需求萎缩、竞争恶化、安全事故）→ bearish_percentage >= 60
4. 影响不明确或两面都有 → sentiment=neutral, 各50
5. affected_stocks 最多列3只最直接受影响的个股代码
6. 仅输出JSON，不要任何解释文字"""

BATCH_SYSTEM_PROMPT = """你是一位专业的A股存储半导体板块分析师。

请分析以下多条新闻对存储板块的影响，为每条新闻逐条输出JSON分析。

每条新闻按以下JSON格式输出：
{
  "news_index": <序号>,
  "sentiment": "bullish" | "bearish" | "neutral",
  "bullish_percentage": <整数>,
  "bearish_percentage": <整数>,
  "confidence": <整数>,
  "affected_stocks": ["<代码>"],
  "reasoning": "<理由，中文，不超50字>"
}

规则：
- bullish_percentage + bearish_percentage = 100
- 明显利好 → bullish >= 60；明显利空 → bearish >= 60
- 影响不明确 → neutral, 各50
- 仅输出JSON数组，不要任何解释文字

A股存储板块代表：兆易创新(603986)、江波龙(301308)、佰维存储(688525)、北京君正(300223)、澜起科技(688008)、深科技(000021)、北方华创(002371)、中微公司(688012)、中芯国际(688981)"""


class SentimentAnalyzer:
    """新闻情绪分析器（带缓存）- 使用 DeepSeek API"""

    def __init__(self, api_key: str | None = None):
        self.api_key = api_key or DEEPSEEK_API_KEY
        self.base_url = DEEPSEEK_BASE_URL
        # 排除占位符
        self._available = bool(self.api_key) and "your-key-here" not in self.api_key and self.api_key.startswith("sk-")

    @property
    def available(self) -> bool:
        return self._available

    def _get_cache(self) -> dict:
        path = SENTIMENT_CACHE_PATTERN.format(date=today_str())
        return load_json(path) or {}

    def _save_cache(self, cache: dict) -> None:
        path = SENTIMENT_CACHE_PATTERN.format(date=today_str())
        save_json(path, cache)

    def _call_api(self, system: str, user: str) -> dict | list | None:
        """调用 DeepSeek API (OpenAI 兼容格式)"""
        if not self.available:
            return None
        try:
            resp = requests.post(
                f"{self.base_url}/chat/completions",
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": DEEPSEEK_MODEL,
                    "messages": [
                        {"role": "system", "content": system},
                        {"role": "user", "content": user},
                    ],
                    "max_tokens": 1024,
                    "temperature": 0.1,
                },
                timeout=30,
            )
            resp.raise_for_status()
            text = resp.json()["choices"][0]["message"]["content"].strip()
            if "```" in text:
                text = text.split("```")[1]
                if text.startswith("json"):
                    text = text[4:]
                text = text.strip()
            return json.loads(text)
        except Exception as e:
            logger.error(f"DeepSeek API call failed: {e}")
            return None

    def analyze_one(self, title: str, content: str) -> dict:
        user_msg = f"新闻标题：{title}\n新闻内容：{content[:500]}"
        result = self._call_api(SYSTEM_PROMPT, user_msg)
        if isinstance(result, dict):
            return result
        return self._default_result()

    def analyze_batch(self, news_items: list[dict]) -> dict[str, dict]:
        cache = self._get_cache()
        results: dict[str, dict] = {}

        uncached = []
        for item in news_items:
            h = item["hash"]
            if h in cache:
                results[h] = cache[h]
            else:
                uncached.append(item)

        if not uncached:
            return results

        if self.available:
            for i in range(0, len(uncached), SENTIMENT_BATCH_SIZE):
                batch = uncached[i : i + SENTIMENT_BATCH_SIZE]
                batch_results = self._analyze_batch_call(batch)
                for j, item in enumerate(batch):
                    h = item["hash"]
                    if j < len(batch_results):
                        result = batch_results[j]
                    else:
                        result = self._default_result()
                    results[h] = result
                    cache[h] = result
            self._save_cache(cache)
        else:
            for item in uncached:
                results[item["hash"]] = self._default_result()

        return results

    def _analyze_batch_call(self, items: list[dict]) -> list[dict]:
        user_lines = []
        for idx, item in enumerate(items, 1):
            user_lines.append(
                f"新闻{idx}:\n标题：{item['title']}\n内容：{item.get('content', '')[:400]}"
            )
        user_msg = "\n\n".join(user_lines)
        result = self._call_api(BATCH_SYSTEM_PROMPT, user_msg)
        if isinstance(result, list):
            return result
        if isinstance(result, dict):
            return [result]
        return []

    def _default_result(self) -> dict:
        return {
            "sentiment": "neutral",
            "bullish_percentage": 50,
            "bearish_percentage": 50,
            "confidence": 0,
            "affected_stocks": [],
            "reasoning": "暂未分析，等待 API 配置",
        }

    def analyze_news_list(self, news_items: list[dict]) -> list[dict]:
        if not news_items:
            return []

        sentiment_map = self.analyze_batch(news_items)
        enriched = []
        for item in news_items:
            s = sentiment_map.get(item["hash"], self._default_result())
            bp = s.get("bullish_percentage", 50)
            bep = s.get("bearish_percentage", 50)
            total = bp + bep
            if total != 100 and total > 0:
                bp = round(bp / total * 100)
                bep = 100 - bp

            enriched.append({
                **item,
                "sentiment": s.get("sentiment", "neutral"),
                "bullish_pct": bp,
                "bearish_pct": bep,
                "confidence": s.get("confidence", 0),
                "affected_stocks": s.get("affected_stocks", []),
                "reasoning": s.get("reasoning", ""),
            })
        return enriched


_analyzer: Optional[SentimentAnalyzer] = None


def get_analyzer() -> SentimentAnalyzer:
    global _analyzer
    if _analyzer is None:
        _analyzer = SentimentAnalyzer()
    return _analyzer
