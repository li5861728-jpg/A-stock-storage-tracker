"""A股存储板块情绪日报 - Streamlit 主应用"""

from __future__ import annotations

import streamlit as st
import pandas as pd
import plotly.graph_objects as go
import traceback

from config import (
    STORAGE_STOCKS,
    REFRESH_INTERVAL_SECONDS,
    NEWS_REFRESH_CYCLES,
    MAX_NEWS_DISPLAY,
)
from src.utils import now_cst, get_market_status, is_trading_hours, format_cst
from src.fetcher import fetch_quotes, fetch_sector_history
from src.news_fetcher import fetch_news
from src.sentiment import get_analyzer

st.set_page_config(
    page_title="存储板块情绪日报",
    page_icon="🏭",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown("""
<style>
    .sentiment-bullish { color: #e53935; font-weight: bold; font-size: 1.1rem; }
    .sentiment-bearish { color: #43a047; font-weight: bold; font-size: 1.1rem; }
    .sentiment-neutral { color: #757575; font-weight: bold; font-size: 1.1rem; }
    .news-card { padding: 12px; margin: 8px 0; border-radius: 8px; border-left: 4px solid #ddd; }
    .news-card.bullish { border-left-color: #e53935; background: #fff5f5; }
    .news-card.bearish { border-left-color: #43a047; background: #f5fff5; }
    .news-card.neutral { border-left-color: #bdbdbd; background: #fafafa; }
    .error-box { background: #fff5f5; border: 1px solid #e53935; border-radius: 8px; padding: 16px; margin: 8px 0; }
</style>
""", unsafe_allow_html=True)

# ============================================================
# Session State
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
# 数据刷新
# ============================================================
def refresh_data(force_news: bool = False) -> None:
    errors = []

    try:
        df = fetch_quotes(use_cache=not force_news)
        if not df.empty:
            st.session_state.quotes_df = df
    except Exception as e:
        errors.append(f"行情获取失败: {str(e)[:80]}")

    try:
        hist = fetch_sector_history(days=20)
        if not hist.empty:
            st.session_state.sector_history = hist
    except Exception as e:
        errors.append(f"板块指数获取失败: {str(e)[:80]}")

    if force_news or st.session_state.cycle_count % NEWS_REFRESH_CYCLES == 0:
        try:
            raw_news = fetch_news(force_refresh=force_news)
            analyzer = get_analyzer()
            enriched = analyzer.analyze_news_list(raw_news)
            st.session_state.news_data = enriched
        except Exception as e:
            errors.append(f"新闻获取失败: {str(e)[:80]}")

    st.session_state.last_refresh = now_cst()
    st.session_state.cycle_count += 1
    st.session_state.errors = errors


# ============================================================
# UI
# ============================================================
def render_header():
    status, status_label = get_market_status()
    is_trading = status == "trading"

    col1, col2, col3 = st.columns([2, 1, 1])
    with col1:
        st.title("A股存储板块情绪日报")
    with col2:
        color = "#e53935" if is_trading else "#888"
        st.markdown(f"### 市场: <span style='color:{color}'>● {status_label}</span>", unsafe_allow_html=True)
    with col3:
        last = st.session_state.last_refresh
        st.markdown(f"**更新**\n\n{format_cst(last) if last else '尚未刷新'}")

    if st.session_state.errors:
        for err in st.session_state.errors:
            st.warning(f"⚠ {err}")


def render_sector_overview():
    df = st.session_state.quotes_df
    if df.empty:
        st.info("暂无行情数据，点击侧边栏「手动刷新」获取")
        return

    up = len(df[df["涨跌幅"] > 0])
    down = len(df[df["涨跌幅"] < 0])
    flat = len(df[df["涨跌幅"] == 0])
    avg = df["涨跌幅"].mean() if not df.empty else 0
    total = df["成交额"].sum() if not df.empty else 0

    cols = st.columns(5)
    cols[0].metric("板块平均涨跌", f"{avg:+.2f}%")
    cols[1].metric("上涨", str(up))
    cols[2].metric("下跌", str(down))
    cols[3].metric("平盘", str(flat))
    cols[4].metric("总成交额", f"{total:.2f}亿")


def render_quote_table():
    df = st.session_state.quotes_df
    if df.empty:
        return
    st.subheader("个股实时行情")
    disp = df[["代码", "名称", "产业链", "最新价", "涨跌幅", "涨跌额", "成交额"]].copy()
    disp = disp.sort_values("涨跌幅", ascending=False)

    def color_change(val):
        if val > 0:
            return "color: #e53935"
        elif val < 0:
            return "color: #43a047"
        return ""

    styled = disp.style.applymap(color_change, subset=["涨跌幅", "涨跌额"])
    styled = styled.format({"最新价": "{:.2f}", "涨跌幅": "{:+.2f}%", "涨跌额": "{:+.2f}", "成交额": "{:.2f}亿"})
    st.dataframe(styled, use_container_width=True, hide_index=True, height=min(38 * len(disp) + 38, 600))


def render_news_feed():
    news = st.session_state.news_data
    if not news:
        st.info("暂无相关新闻，点击「手动刷新」获取")
        return

    st.subheader(f"板块新闻 · 情绪分析（{len(news)} 条）")

    for item in news[:MAX_NEWS_DISPLAY]:
        bp = item.get("bullish_pct", 50)
        bep = item.get("bearish_pct", 50)
        sentiment = item.get("sentiment", "neutral")
        reasoning = item.get("reasoning", "")

        if sentiment == "bullish":
            emoji, pct_text, css_class, sc = "🔴", f"利好 {bp}%", "bullish", "sentiment-bullish"
        elif sentiment == "bearish":
            emoji, pct_text, css_class, sc = "🟢", f"利空 {bep}%", "bearish", "sentiment-bearish"
        else:
            emoji, pct_text, css_class, sc = "⚪", "中性 50%", "neutral", "sentiment-neutral"

        st.markdown(f"""
        <div class="news-card {css_class}">
            <div style="display:flex;justify-content:space-between;align-items:center">
                <strong>{emoji} {item['title']}</strong>
                <span class="{sc}">{pct_text}</span>
            </div>
            <div style="margin-top:6px;color:#555;font-size:0.9rem">{item.get('content','')[:200]}</div>
            <div style="margin-top:6px;display:flex;justify-content:space-between;color:#999;font-size:0.8rem">
                <span>{item.get('source','未知')} | {item.get('pub_time','')}</span>
                <span>{reasoning}</span>
            </div>
            <div style="margin-top:4px"><div style="display:flex;height:4px;border-radius:2px;overflow:hidden">
                <div style="width:{bp}%;background:#e53935"></div>
                <div style="width:{bep}%;background:#43a047"></div>
            </div></div>
        </div>
        """, unsafe_allow_html=True)


def render_sector_chart():
    hist = st.session_state.sector_history
    if hist.empty:
        return

    st.subheader("半导体板块指数（近20日）")
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=hist["日期"], y=hist["收盘"], mode="lines+markers",
        name="收盘价", line=dict(color="#e53935", width=2), marker=dict(size=4)))
    if "成交量" in hist.columns:
        fig.add_trace(go.Bar(x=hist["日期"], y=hist["成交量"], name="成交量",
            yaxis="y2", marker=dict(color="rgba(200,200,200,0.5)")))
    fig.update_layout(xaxis_title="日期", yaxis_title="收盘价",
        yaxis2=dict(title="成交量", overlaying="y", side="right", showgrid=False),
        hovermode="x unified", height=350, margin=dict(l=10, r=10, t=10, b=10),
        legend=dict(orientation="h", yanchor="bottom", y=1.02))
    st.plotly_chart(fig, use_container_width=True)


def render_sidebar():
    with st.sidebar:
        st.header("控制面板")

        if st.button("手动刷新", use_container_width=True):
            with st.spinner("刷新中..."):
                refresh_data(force_news=True)
            st.rerun()

        is_trading = is_trading_hours()
        if is_trading:
            st.success("当前为交易时间")
        else:
            st.info("非交易时间")

        analyzer = get_analyzer()
        if analyzer.available:
            st.success("DeepSeek API 已配置")
        else:
            st.warning("DeepSeek API 未配置")

        st.divider()
        st.caption(f"股票: {len(STORAGE_STOCKS)} 只 | 新闻: {len(st.session_state.news_data)} 条")
        st.caption(f"刷新: {st.session_state.cycle_count} 次")
        if st.session_state.last_refresh:
            st.caption(f"上次: {format_cst(st.session_state.last_refresh)}")

        with st.expander("追踪列表"):
            for s in STORAGE_STOCKS:
                st.caption(f"{s['code']} {s['name']} · {s['sector']}")


# ============================================================
def main():
    try:
        render_sidebar()
        render_header()
        st.divider()

        if st.session_state.quotes_df.empty and st.session_state.last_refresh is None:
            with st.spinner("正在获取实时数据..."):
                refresh_data(force_news=True)

        render_sector_overview()
        st.divider()

        col_left, col_right = st.columns([2, 3])
        with col_left:
            render_sector_chart()
        with col_right:
            render_quote_table()

        st.divider()
        render_news_feed()

    except Exception as e:
        st.error(f"页面渲染出错，请点击「手动刷新」重试")
        st.markdown(f"""
        <div class="error-box">
            <strong>错误详情:</strong><br>
            <pre style="white-space:pre-wrap;font-size:0.8rem">{traceback.format_exc()}</pre>
        </div>
        """, unsafe_allow_html=True)


if __name__ == "__main__":
    main()
