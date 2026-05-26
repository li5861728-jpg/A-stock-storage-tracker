"""实时行情获取 - AKShare + 腾讯行情备用"""

from __future__ import annotations

import logging
import pandas as pd
import requests
from datetime import datetime
from typing import Optional

from config import STORAGE_STOCKS, QUOTES_CACHE
from src.utils import now_cst, load_json, save_json

logger = logging.getLogger(__name__)

# 目标股票代码集合（纯数字）
TARGET_CODES = {s["code"] for s in STORAGE_STOCKS}
CODE_TO_INFO = {s["code"]: s for s in STORAGE_STOCKS}


def _normalize_code(code: str) -> str:
    """统一为6位数字代码"""
    return code.replace("sh", "").replace("sz", "").replace("SH", "").replace("SZ", "")


def _market_prefix(code: str) -> str:
    """根据代码判断交易所前缀: sh 或 sz"""
    c = _normalize_code(code)
    if c.startswith(("6", "9")):
        return f"sh{c}"
    elif c.startswith(("0", "3")):
        return f"sz{c}"
    return c


def fetch_quotes_akshare() -> pd.DataFrame:
    """通过 AKShare 获取全市场实时行情，筛选出存储板块股票"""
    try:
        import akshare as ak
        df = ak.stock_zh_a_spot_em()
        df["code"] = df["代码"].astype(str).str.zfill(6)
        df = df[df["code"].isin(TARGET_CODES)].copy()
        if df.empty:
            logger.warning("AKShare returned no matching stocks")
            return pd.DataFrame()
        return df
    except Exception as e:
        logger.error(f"AKShare fetch failed: {e}")
        raise


def _parse_tencent_quote(text: str) -> dict:
    """解析腾讯行情 API 返回的单条数据"""
    try:
        # 格式: v_sh600519="1~贵州茅台~600519~1850.00~..."
        parts = text.split("~")
        if len(parts) < 40:
            return {}
        return {
            "name": parts[1],
            "code": parts[2],
            "price": float(parts[3]) if parts[3] else 0,
            "prev_close": float(parts[4]) if parts[4] else 0,
            "open": float(parts[5]) if parts[5] else 0,
            "volume": float(parts[6]) if parts[6] else 0,  # 手
            "amount": float(parts[37]) if len(parts) > 37 and parts[37] else 0,  # 万元
            "change_pct": float(parts[32]) if len(parts) > 32 and parts[32] else 0,
        }
    except (ValueError, IndexError):
        return {}


def fetch_quotes_tencent() -> pd.DataFrame:
    """通过腾讯行情 API 获取实时报价（备用方案）"""
    codes = [_market_prefix(c) for c in TARGET_CODES]
    url = "https://qt.gtimg.cn/q=" + ",".join(codes)
    try:
        resp = requests.get(url, timeout=10)
        resp.encoding = "gbk"
        results = []
        for line in resp.text.strip().split("\n"):
            line = line.strip()
            if not line or "=" not in line:
                continue
            data = _parse_tencent_quote(line.split("=", 1)[1].strip('";'))
            if data:
                results.append(data)
        df = pd.DataFrame(results)
        if df.empty:
            return df
        df["code"] = df["code"].astype(str).str.zfill(6)
        df["最新价"] = df["price"]
        df["涨跌幅"] = df["change_pct"]
        df["成交量"] = df["volume"]
        df["成交额"] = df["amount"]
        df["今开"] = df["open"]
        df["昨收"] = df["prev_close"]
        return df
    except Exception as e:
        logger.error(f"Tencent fetch failed: {e}")
        raise


def fetch_quotes(use_cache: bool = True) -> pd.DataFrame:
    """获取存储板块股票实时行情（带缓存和容错）"""
    cache_age = 0
    if use_cache:
        cached = load_json(QUOTES_CACHE)
        if cached and isinstance(cached, dict):
            cache_time = cached.get("timestamp")
            if cache_time:
                cache_age = (now_cst() - datetime.fromisoformat(cache_time)).total_seconds()
                if cache_age < 60:  # 1 分钟内的缓存直接用
                    df = pd.DataFrame(cached.get("data", []))
                    if not df.empty:
                        return df

    for attempt, fetcher in enumerate([fetch_quotes_akshare, fetch_quotes_tencent]):
        try:
            df = fetcher()
            if df is not None and not df.empty:
                break
        except Exception:
            if attempt == 1:
                # 两个源都失败了，尝试用缓存
                cached = load_json(QUOTES_CACHE)
                if cached and isinstance(cached, dict):
                    df = pd.DataFrame(cached.get("data", []))
                    if not df.empty:
                        return df
                return pd.DataFrame()
            continue

    # 整理为标准格式
    result = _normalize_quotes_df(df)
    if not result.empty:
        _cache_quotes(result)
    return result


def _normalize_quotes_df(df: pd.DataFrame) -> pd.DataFrame:
    """统一行情 DataFrame 格式"""
    records = []
    for _, row in df.iterrows():
        code = str(row.get("code", row.get("代码", ""))).zfill(6)
        if code not in TARGET_CODES:
            continue
        info = CODE_TO_INFO.get(code, {})
        price = float(row.get("最新价", row.get("price", 0)) or 0)
        change_pct = float(row.get("涨跌幅", row.get("change_pct", 0)) or 0)
        volume = float(row.get("成交量", row.get("volume", 0)) or 0)
        amount = float(row.get("成交额", row.get("amount", 0)) or 0)
        # 成交额单位可能是万元，统一转为亿元
        if amount > 0 and amount < 1000:
            amount = amount / 10000  # 万元 -> 亿元

        records.append({
            "代码": code,
            "名称": info.get("name", row.get("名称", row.get("name", ""))),
            "产业链": info.get("sector", ""),
            "最新价": round(price, 2),
            "涨跌幅": round(change_pct, 2),
            "成交量": int(volume),
            "成交额": round(amount, 2),
            "涨跌额": round(price * change_pct / 100, 2) if price > 0 and change_pct != 0 else 0,
        })

    return pd.DataFrame(records)


def _cache_quotes(df: pd.DataFrame) -> None:
    """缓存实时行情"""
    save_json(QUOTES_CACHE, {
        "timestamp": now_cst().isoformat(),
        "data": df.to_dict(orient="records"),
    })


def fetch_sector_history(days: int = 20) -> pd.DataFrame:
    """获取半导体板块指数历史数据"""
    try:
        import akshare as ak
        end_date = now_cst().strftime("%Y%m%d")
        df = ak.stock_board_industry_hist_em(
            symbol="半导体",
            start_date=(now_cst().replace(day=1) if days > 30 else now_cst()).strftime("%Y%m%d"),
            end_date=end_date,
            adjust="",
        )
        if df is not None and not df.empty:
            df = df.tail(days)
            df["日期"] = pd.to_datetime(df["日期"])
            return df
    except Exception as e:
        logger.error(f"Failed to fetch sector history: {e}")
    return pd.DataFrame()


def get_stock_list() -> list[dict]:
    """返回股票列表"""
    return STORAGE_STOCKS
