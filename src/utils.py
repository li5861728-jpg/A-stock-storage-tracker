"""交易时间判断、时区工具、日志工具"""

from __future__ import annotations

from datetime import datetime, time
import pytz
import hashlib
import json
import os

CST = pytz.timezone("Asia/Shanghai")


def now_cst() -> datetime:
    """获取当前北京时间"""
    return datetime.now(CST)


def is_trading_day(dt: datetime | None = None) -> bool:
    """判断是否为交易日（周一至周五，排除中国法定节假日）"""
    if dt is None:
        dt = now_cst()
    # 周末
    if dt.weekday() >= 5:
        return False
    # TODO: 接入法定节假日数据（春节、国庆等）
    return True


def is_trading_hours(dt: datetime | None = None) -> bool:
    """判断是否在交易时间内（9:30-11:30, 13:00-15:00 CST）"""
    if not is_trading_day(dt):
        return False
    if dt is None:
        dt = now_cst()
    t = dt.time()
    morning = time(9, 30) <= t <= time(11, 30)
    afternoon = time(13, 0) <= t <= time(15, 0)
    return morning or afternoon


def get_market_status() -> tuple[str, str]:
    """
    返回 (状态标签, 状态描述)
    状态: trading, lunch_break, closed_weekend, closed_holiday, closed_after_hours
    """
    now = now_cst()
    t = now.time()

    if not is_trading_day(now):
        return "closed_weekend", "周末休市"

    if time(9, 30) <= t <= time(11, 30):
        return "trading", "交易中"
    elif time(11, 30) < t < time(13, 0):
        return "lunch_break", "午间休市"
    elif time(13, 0) <= t <= time(15, 0):
        return "trading", "交易中"
    elif t < time(9, 30):
        return "closed_before", "盘前"
    else:
        return "closed_after", "盘后"


def get_market_open_today() -> bool:
    """今天是否开市（简化判断，不含节假日）"""
    return is_trading_day()


def format_cst(dt: datetime) -> str:
    """格式化为北京时间字符串"""
    if dt.tzinfo is None:
        dt = CST.localize(dt)
    return dt.strftime("%Y-%m-%d %H:%M:%S CST")


def today_str() -> str:
    """返回今日日期字符串 YYYYMMDD"""
    return now_cst().strftime("%Y%m%d")


def news_hash(title: str) -> str:
    """计算新闻标题的 MD5 哈希，用于去重"""
    return hashlib.md5(title.strip().encode("utf-8")).hexdigest()


def load_json(path: str) -> dict | list | None:
    """安全加载 JSON 文件"""
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return None


def save_json(path: str, data: dict | list) -> None:
    """保存 JSON 文件"""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2, default=str)
