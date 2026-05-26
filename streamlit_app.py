"""A股存储板块情绪日报 - Streamlit 主应用"""

from __future__ import annotations

import streamlit as st
import traceback

from config import MAX_NEWS_DISPLAY
from src.utils import now_cst, get_market_status, is_trading_hours, format_cst
from src.news_fetcher import fetch_news
from src.sentiment import get_analyzer

st.set_page_config(
    page_title="存储板块信息情绪日报",
    page_icon="📰",
    layout="wide",
    initial_sidebar_state="collapsed",
)

st.markdown("""
<style>
    .sentiment-bullish { color: #e53935; font-weight: bold; font-size: 1.2rem; }
    .sentiment-bearish { color: #43a047; font-weight: bold; font-size: 1.2rem; }
    .sentiment-neutral { color: #757575; font-weight: bold; font-size: 1.2rem; }
    .news-card { padding: 18px 20px; margin: 12px 0; border-radius: 10px; border-left: 5px solid #ddd; }
    .news-card.bullish { border-left-color: #e53935; background: #fff8f8; }
    .news-card.bearish { border-left-color: #43a047; background: #f5fff5; }
    .news-card.neutral { border-left-color: #bdbdbd; background: #fafafa; }
    .pct-bar { display: flex; height: 6px; border-radius: 3px; overflow: hidden; margin-top: 8px; }
    .meta-text { color: #999; font-size: 0.82rem; }
    .news-title { font-size: 1.08rem; line-height: 1.5; }
    .news-content { color: #555; font-size: 0.92rem; line-height: 1.6; margin-top: 8px; }
</style>
""", unsafe_allow_html=True)

# ============================================================
if "news_data" not in st.session_state:
    st.session_state.news_data = []
    st.session_state.last_refresh = None
    st.session_state.errors = []


def refresh():
    errors = []
    try:
        raw = fetch_news(force_refresh=True)
        analyzer = get_analyzer()
        st.session_state.news_data = analyzer.analyze_news_list(raw)
    except Exception as e:
        errors.append(f"新闻获取失败: {str(e)[:100]}")
    st.session_state.last_refresh = now_cst()
    st.session_state.errors = errors


def render_news_card(item: dict):
    bp = item.get("bullish_pct", 50)
    bep = item.get("bearish_pct", 50)
    sentiment = item.get("sentiment", "neutral")
    reasoning = item.get("reasoning", "")
    content = item.get("content", "")
    source = item.get("source", "")
    pub_time = item.get("pub_time", "")

    if sentiment == "bullish":
        emoji, pct_text, css, sc = "📈", f"利好 {bp}%", "bullish", "sentiment-bullish"
    elif sentiment == "bearish":
        emoji, pct_text, css, sc = "📉", f"利空 {bep}%", "bearish", "sentiment-bearish"
    else:
        emoji, pct_text, css, sc = "➖", f"中性 {bp}%", "neutral", "sentiment-neutral"

    st.markdown(f"""
    <div class="news-card {css}">
        <div style="display:flex;justify-content:space-between;align-items:flex-start;gap:20px">
            <div style="flex:1">
                <div class="news-title"><strong>{emoji} {item['title']}</strong></div>
                {f'<div class="news-content">{content[:300]}</div>' if content else ''}
                <div style="margin-top:8px">
                    <span class="meta-text">{source}</span>
                    <span class="meta-text" style="margin-left:12px">{pub_time}</span>
                    {f'<span class="meta-text" style="margin-left:12px;color:#666">💡 {reasoning}</span>' if reasoning and reasoning != '暂未分析，等待 API 配置' else ''}
                </div>
            </div>
            <div style="text-align:center;min-width:80px">
                <span class="{sc}">{pct_text}</span>
                <div class="pct-bar">
                    <div style="width:{bp}%;background:#e53935"></div>
                    <div style="width:{bep}%;background:#43a047"></div>
                </div>
            </div>
        </div>
    </div>
    """, unsafe_allow_html=True)


# ============================================================
def main():
    try:
        # Header
        status, label = get_market_status()
        is_trading = status == "trading"
        color = "#e53935" if is_trading else "#888"

        col1, col2, col3 = st.columns([3, 1, 1])
        with col1:
            st.title("📰 存储板块信息 · 情绪日报")
            st.caption("客观汇总公开平台最新信息，AI 分析对存储板块的利好/利空影响")
        with col2:
            st.markdown(f"### 市场: <span style='color:{color}'>● {label}</span>", unsafe_allow_html=True)
        with col3:
            if st.button("🔄 刷新信息", use_container_width=True, type="primary"):
                with st.spinner("正在获取最新信息..."):
                    refresh()
                st.rerun()

        # 更新时间
        last = st.session_state.last_refresh
        if last:
            st.caption(f"更新时间: {format_cst(last)} · 刷新页面获取最新")
        else:
            st.caption("点击「刷新信息」获取最新资讯")

        # 自动首次加载
        if not st.session_state.news_data and last is None:
            with st.spinner("正在获取最新信息..."):
                refresh()
            st.rerun()

        if st.session_state.errors:
            for e in st.session_state.errors:
                st.warning(f"⚠ {e}")

        st.divider()

        # 新闻流
        news = st.session_state.news_data
        if not news:
            st.info("暂无相关信息，请点击「刷新信息」按钮获取")
            return

        # 统计
        bullish_count = sum(1 for n in news if n.get("sentiment") == "bullish")
        bearish_count = sum(1 for n in news if n.get("sentiment") == "bearish")
        neutral_count = sum(1 for n in news if n.get("sentiment") == "neutral")

        c1, c2, c3, c4 = st.columns(4)
        c1.metric("信息总数", str(len(news)))
        c2.metric("📈 利好", str(bullish_count))
        c3.metric("📉 利空", str(bearish_count))
        c4.metric("➖ 中性", str(neutral_count))

        st.divider()

        # 筛选
        filt = st.radio("筛选", ["全部", "利好", "利空", "中性"], horizontal=True, label_visibility="collapsed")
        for item in news[:MAX_NEWS_DISPLAY]:
            s = item.get("sentiment", "neutral")
            if filt == "利好" and s != "bullish":
                continue
            if filt == "利空" and s != "bearish":
                continue
            if filt == "中性" and s != "neutral":
                continue
            render_news_card(item)

        # Footer
        st.divider()
        st.caption(f"共 {len(news)} 条信息 · 来源: 财联社 / 东方财富 / 新浪财经 · 情绪分析由 AI 生成，仅供参考")

    except Exception:
        st.error("页面出错，请点击「刷新信息」重试")
        st.markdown(f"<pre style='font-size:0.75rem'>{traceback.format_exc()}</pre>", unsafe_allow_html=True)


if __name__ == "__main__":
    main()
