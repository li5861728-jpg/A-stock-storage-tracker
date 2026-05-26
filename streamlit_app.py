"""A股存储板块情绪日报 - Streamlit 主应用"""

from __future__ import annotations

import streamlit as st
import pandas as pd
import plotly.graph_objects as go
import os
from datetime import datetime
from streamlit_autorefresh import st_autorefresh

from config import (
    STORAGE_STOCKS,
    REFRESH_INTERVAL_SECONDS,
    NEWS_REFRESH_CYCLES,
    MAX_NEWS_DISPLAY,
    CACHE_DIR,
)
from src.utils import now_cst, get_market_status, is_trading_hours, format_cst, today_str
from src.fetcher import fetch_quotes, fetch_sector_history
from src.news_fetcher import fetch_news
from src.sentiment import get_analyzer

# ============================================================
# 页面配置
# ============================================================
st.set_page_config(
    page_title="存储板块情绪日报",
    page_icon="🏭",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ============================================================
# 样式
# ============================================================
st.markdown("""
<style>
    .sentiment-bullish { color: #e53935; font-weight: bold; font-size: 1.1rem; }
    .sentiment-bearish { color: #43a047; font-weight: bold; font-size: 1.1rem; }
    .sentiment-neutral { color: #757575; font-weight: bold; font-size: 1.1rem; }
    .news-card { padding: 12px; margin: 8px 0; border-radius: 8px; border-left: 4px solid #ddd; }
    .news-card.bullish { border-left-color: #e53935; background: #fff5f5; }
    .news-card.bearish { border-left-color: #43a047; background: #f5fff5; }
    .news-card.neutral { border-left-color: #bdbdbd; background: #fafafa; }
</style>
""", unsafe_allow_html=True)

# ============================================================
# 初始化 Session State
# ============================================================
if "init" not in st.session_state:
    st.session_state.init = True
    st.session_state.cycle_count = 0
    st.session_state.last_refresh = None
    st.session_state.quotes_df = pd.DataFrame()
    st.session_state.news_data = []
    st.session_state.sector_history = pd.DataFrame()
    st.session_state.errors = []
    st.session_state.auto_refresh = False


# ============================================================
# 数据刷新逻辑
# ============================================================
def refresh_data(force_news: bool = False) -> None:
    """刷新行情和新闻数据"""
    errors = []

    # 行情
    try:
        df = fetch_quotes(use_cache=not force_news)
        if not df.empty:
            st.session_state.quotes_df = df
    except Exception as e:
        errors.append(f"行情获取: {e}")

    # 板块指数
    try:
        hist = fetch_sector_history(days=20)
        if not hist.empty:
            st.session_state.sector_history = hist
    except Exception as e:
        errors.append(f"板块指数: {e}")

    # 新闻（首次或手动刷新时拉取）
    if force_news or st.session_state.cycle_count % NEWS_REFRESH_CYCLES == 0:
        try:
            raw_news = fetch_news(force_refresh=force_news)
            analyzer = get_analyzer()
            enriched = analyzer.analyze_news_list(raw_news)
            st.session_state.news_data = enriched
        except Exception as e:
            errors.append(f"新闻获取: {e}")

    st.session_state.last_refresh = now_cst()
    st.session_state.cycle_count += 1
    st.session_state.errors = errors


# ============================================================
# UI 组件
# ============================================================
def render_header() -> None:
    """顶部状态栏"""
    status, status_label = get_market_status()
    is_trading = status == "trading"

    col1, col2, col3 = st.columns([2, 1, 1])
    with col1:
        st.title("A股存储板块情绪日报")
    with col2:
        color = "#e53935" if is_trading else "#888"
        st.markdown(
            f"### 市场状态: <span style='color:{color}'>● {status_label}</span>",
            unsafe_allow_html=True,
        )
    with col3:
        last = st.session_state.last_refresh
        if last:
            st.markdown(f"**更新时间**\n\n{format_cst(last)}")
        else:
            st.markdown("**更新时间**\n\n尚未刷新")

    if st.session_state.errors:
        for err in st.session_state.errors:
            st.warning(f"⚠️ {err}（使用缓存数据）")


def render_sector_overview() -> None:
    """板块概览 KPI 行"""
    df = st.session_state.quotes_df
    if df.empty:
        st.info("暂无行情数据，点击侧边栏「手动刷新」获取数据")
        return

    up_count = len(df[df["涨跌幅"] > 0])
    down_count = len(df[df["涨跌幅"] < 0])
    flat_count = len(df[df["涨跌幅"] == 0])
    avg_change = df["涨跌幅"].mean() if not df.empty else 0
    total_amount = df["成交额"].sum() if not df.empty else 0

    cols = st.columns(5)
    cols[0].metric("板块平均涨跌", f"{avg_change:+.2f}%")
    cols[1].metric("上涨家数", str(up_count))
    cols[2].metric("下跌家数", str(down_count))
    cols[3].metric("平盘家数", str(flat_count))
    cols[4].metric("总成交额", f"{total_amount:.2f} 亿")


def render_quote_table() -> None:
    """个股行情表格"""
    df = st.session_state.quotes_df
    if df.empty:
        return

    st.subheader("个股实时行情")

    display_df = df[["代码", "名称", "产业链", "最新价", "涨跌幅", "涨跌额", "成交额"]].copy()
    display_df = display_df.sort_values("涨跌幅", ascending=False)

    def color_change(val):
        if val > 0:
            return "color: #e53935"
        elif val < 0:
            return "color: #43a047"
        return ""

    styled = display_df.style.applymap(color_change, subset=["涨跌幅", "涨跌额"])
    styled = styled.format({
        "最新价": "{:.2f}",
        "涨跌幅": "{:+.2f}%",
        "涨跌额": "{:+.2f}",
        "成交额": "{:.2f}亿",
    })

    st.dataframe(
        styled,
        use_container_width=True,
        hide_index=True,
        height=min(38 * len(display_df) + 38, 600),
    )


def render_news_feed() -> None:
    """新闻情绪分析卡片"""
    news = st.session_state.news_data
    if not news:
        st.info("暂无相关新闻，点击侧边栏「手动刷新」获取")
        return

    st.subheader(f"板块新闻 · 情绪分析（共 {len(news)} 条）")

    for item in news[:MAX_NEWS_DISPLAY]:
        bp = item.get("bullish_pct", 50)
        bep = item.get("bearish_pct", 50)
        sentiment = item.get("sentiment", "neutral")
        reasoning = item.get("reasoning", "")

        if sentiment == "bullish":
            emoji = "🔴"
            pct_text = f"利好 {bp}%"
            css_class = "bullish"
            sentiment_class = "sentiment-bullish"
        elif sentiment == "bearish":
            emoji = "🟢"
            pct_text = f"利空 {bep}%"
            css_class = "bearish"
            sentiment_class = "sentiment-bearish"
        else:
            emoji = "⚪"
            pct_text = "中性 50%"
            css_class = "neutral"
            sentiment_class = "sentiment-neutral"

        with st.container():
            st.markdown(f"""
            <div class="news-card {css_class}">
                <div style="display: flex; justify-content: space-between; align-items: center;">
                    <strong style="font-size: 1.05rem;">{emoji} {item['title']}</strong>
                    <span class="{sentiment_class}">{pct_text}</span>
                </div>
                <div style="margin-top: 6px; color: #555; font-size: 0.9rem;">
                    {item.get('content', '')[:200]}
                </div>
                <div style="margin-top: 6px; display: flex; justify-content: space-between; color: #999; font-size: 0.8rem;">
                    <span>来源: {item.get('source', '未知')} | {item.get('pub_time', '')}</span>
                    <span>{reasoning}</span>
                </div>
                <div style="margin-top: 4px;">
                    <div style="display: flex; height: 4px; border-radius: 2px; overflow: hidden;">
                        <div style="width:{bp}%; background: #e53935;"></div>
                        <div style="width:{bep}%; background: #43a047;"></div>
                    </div>
                </div>
            </div>
            """, unsafe_allow_html=True)


def render_sector_chart() -> None:
    """板块走势图"""
    hist = st.session_state.sector_history
    if hist.empty:
        return

    st.subheader("半导体板块指数（近20日）")

    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=hist["日期"],
        y=hist["收盘"],
        mode="lines+markers",
        name="收盘价",
        line=dict(color="#e53935", width=2),
        marker=dict(size=4),
    ))

    if "成交量" in hist.columns:
        fig.add_trace(go.Bar(
            x=hist["日期"],
            y=hist["成交量"],
            name="成交量",
            yaxis="y2",
            marker=dict(color="rgba(200,200,200,0.5)"),
        ))

    fig.update_layout(
        xaxis_title="日期",
        yaxis_title="收盘价",
        yaxis2=dict(title="成交量", overlaying="y", side="right", showgrid=False),
        hovermode="x unified",
        height=350,
        margin=dict(l=10, r=10, t=10, b=10),
        legend=dict(orientation="h", yanchor="bottom", y=1.02),
    )

    st.plotly_chart(fig, use_container_width=True)


def render_sidebar() -> None:
    """侧边栏控制"""
    with st.sidebar:
        st.header("控制面板")

        col1, col2 = st.columns(2)
        with col1:
            if st.button("手动刷新", use_container_width=True):
                with st.spinner("刷新中..."):
                    refresh_data(force_news=True)
                st.rerun()
        with col2:
            auto = st.session_state.auto_refresh
            label = "停止自动" if auto else "开启自动刷新"
            if st.button(label, use_container_width=True):
                st.session_state.auto_refresh = not auto
                if not auto:
                    st.session_state.cycle_count = 0
                st.rerun()

        st.divider()
        if st.session_state.auto_refresh:
            is_trading = is_trading_hours()
            if is_trading:
                st.success(f"自动刷新中 · 每 {REFRESH_INTERVAL_SECONDS // 60} 分钟")
            else:
                st.info("非交易时间，数据已缓存")
        else:
            is_trading = is_trading_hours()
            if is_trading:
                st.caption("当前为交易时间，可开启自动刷新")

        # API 状态
        analyzer = get_analyzer()
        if analyzer.available:
            st.success("DeepSeek API 已配置")
        else:
            st.warning("DeepSeek API 未配置\n\n在 Streamlit Cloud → Settings → Secrets 添加:\n\nDEEPSEEK_API_KEY = \"sk-...\"\n\n当前新闻显示中性情绪")

        st.divider()
        st.caption(f"追踪股票: {len(STORAGE_STOCKS)} 只")
        st.caption(f"新闻条数: {len(st.session_state.news_data)}")
        st.caption(f"刷新次数: {st.session_state.cycle_count}")
        if st.session_state.last_refresh:
            st.caption(f"上次刷新: {format_cst(st.session_state.last_refresh)}")

        st.divider()
        with st.expander("追踪列表"):
            for s in STORAGE_STOCKS:
                st.caption(f"{s['code']} {s['name']} · {s['sector']}")


# ============================================================
# 主入口
# ============================================================
def main():
    # 自动刷新（使用 streamlit-autorefresh，Streamlit Cloud 兼容）
    if st.session_state.auto_refresh:
        limit = REFRESH_INTERVAL_SECONDS * 1000  # 转换为毫秒
    else:
        limit = 999999999  # 不触发自动刷新

    st_autorefresh(interval=limit, key="auto_refresh_timer")

    render_sidebar()
    render_header()
    st.divider()

    # 初始加载
    if st.session_state.quotes_df.empty and st.session_state.last_refresh is None:
        with st.spinner("正在获取实时数据..."):
            refresh_data(force_news=True)

    # 自动刷新时的数据更新
    if st.session_state.auto_refresh and st.session_state.last_refresh:
        elapsed = (now_cst() - st.session_state.last_refresh).total_seconds()
        if elapsed >= REFRESH_INTERVAL_SECONDS - 10:
            refresh_data(force_news=False)

    render_sector_overview()
    st.divider()

    col_left, col_right = st.columns([2, 3])
    with col_left:
        render_sector_chart()
    with col_right:
        render_quote_table()

    st.divider()
    render_news_feed()


if __name__ == "__main__":
    main()
