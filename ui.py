"""Visual layer: custom CSS and small HTML building blocks for the Streamlit app.

Colours and fonts come from .streamlit/config.toml; this adds the pieces a
theme can't express (hero banner, card headers, metric tiles, pill tabs).
"""
import html
import re

import streamlit as st

CSS = """
<style>
.block-container { padding-top: 2rem; max-width: 1240px; }

/* ---------- hero ---------- */
.hero {
  position: relative; overflow: hidden;
  border: 1px solid rgba(255,255,255,.08); border-radius: 24px;
  padding: 28px 32px 24px; margin-bottom: 20px;
  background:
    radial-gradient(900px 380px at 0% -10%, rgba(124,92,255,.55), transparent 60%),
    radial-gradient(700px 360px at 100% 0%, rgba(34,211,166,.32), transparent 60%),
    linear-gradient(135deg, #131b3a 0%, #0c1229 100%);
}
.hero .eyebrow { text-transform: uppercase; letter-spacing: .16em; font-size: .75rem;
  font-weight: 600; color: #8ff0d4; margin-bottom: 8px; }
.hero h1 { font-family: 'Space Grotesk', sans-serif; font-size: 2.05rem; line-height: 1.15;
  margin: 0; padding: 0; font-weight: 700;
  background: linear-gradient(90deg, #ffffff 0%, #c9c0ff 55%, #8ff0d4 100%);
  -webkit-background-clip: text; background-clip: text; color: transparent; }
.hero p { color: #c3cbe6; font-size: .95rem; max-width: 780px; margin: 12px 0 18px; line-height: 1.55; }
.chips { display: flex; flex-wrap: wrap; gap: 8px; }
.chip { padding: 5px 12px; border-radius: 999px; font-size: .78rem; color: #e3e8ff;
  background: rgba(255,255,255,.07); border: 1px solid rgba(255,255,255,.12); }
.chip b { color: #8ff0d4; font-weight: 600; }

/* ---------- ticker header ---------- */
.ticker { display: flex; align-items: baseline; gap: 14px; flex-wrap: wrap; }
.ticker .sym { font-family: 'Space Grotesk', sans-serif; font-size: 1.6rem; font-weight: 700; letter-spacing: -.01em; }
.ticker .meta { color: #a3add0; font-size: .88rem; }
.ticker .meta b { color: #e7ecff; font-weight: 600; }
.up { color: #34d6a6; } .down { color: #ff7a7a; }

/* ---------- tabs as pills ---------- */
.stTabs [data-baseweb="tab-list"] { gap: 6px; padding: 6px; border-radius: 16px;
  background: rgba(255,255,255,.03); border: 1px solid rgba(255,255,255,.07); }
.stTabs [data-baseweb="tab"] { height: auto; padding: 7px 16px; border-radius: 10px; }
.stTabs [data-baseweb="tab"] p { font-weight: 600; font-size: .86rem; color: #c3cbe6; }
.stTabs [aria-selected="true"] p { color: #ffffff; }
.stTabs [aria-selected="true"] { background: rgba(255,255,255,.09); box-shadow: inset 0 -2px 0 #3ddbc0; }
.stTabs [data-baseweb="tab-highlight"], .stTabs [data-baseweb="tab-border"] { display: none; }

/* ---------- metric tiles ---------- */
[data-testid="stMetric"] {
  border-radius: 16px; padding: 13px 16px 12px;
  background: linear-gradient(180deg, rgba(255,255,255,.055), rgba(255,255,255,.015));
  border: 1px solid rgba(255,255,255,.08);
  box-shadow: inset 0 1px 0 rgba(255,255,255,.05);
}
[data-testid="stMetricLabel"] p { color: #a3add0; font-weight: 500; font-size: .8rem; }
[data-testid="stMetricValue"] { font-family: 'Space Grotesk', sans-serif; font-weight: 600; font-size: 1.5rem; }

/* ---------- section cards ---------- */
[data-testid="stVerticalBlockBorderWrapper"] { border-radius: 20px !important; background: rgba(255,255,255,.018); }
.sec { display: flex; gap: 14px; align-items: flex-start; margin: 4px 2px 6px; }
.sec .num { flex: none; width: 30px; height: 30px; border-radius: 9px; font-size: .9rem; display: grid; place-items: center;
  font-family: 'Space Grotesk', sans-serif; font-weight: 700; color: #fff;
  background: linear-gradient(135deg, #7c5cff, #22d3a6); box-shadow: 0 6px 18px rgba(124,92,255,.35); }
.sec h4 { margin: 2px 0 0; padding: 0; font-size: 1.05rem; }
.sec .desc { color: #b4bddc; font-size: .84rem; line-height: 1.55; margin-top: 6px; }
.sec .desc .k { color: #e7ecff; font-weight: 600; }
.sec .desc b { color: #e7ecff; }
.sw { display: inline-block; width: 10px; height: 10px; border-radius: 3px; margin: 0 3px 0 1px; vertical-align: 0; }

/* ---------- misc ---------- */
.period { display: inline-block; padding: 3px 11px; border-radius: 999px; font-size: .78rem; font-weight: 600;
  color: #e7ecff; background: rgba(61,219,192,.10); border: 1px solid rgba(61,219,192,.40); margin: 4px 0 10px; }
[data-testid="stSidebar"] h2 { font-family: 'Space Grotesk', sans-serif; }
.side-brand { font-family: 'Space Grotesk', sans-serif; font-weight: 700; font-size: 1rem; margin-bottom: 2px;
  background: linear-gradient(90deg, #c9c0ff, #8ff0d4); -webkit-background-clip: text; background-clip: text; color: transparent; }
</style>
"""


def inject_css() -> None:
    st.markdown(CSS, unsafe_allow_html=True)


def _md_inline(text: str) -> str:
    """Escape, then render the tiny subset of markdown used in descriptions."""
    out = html.escape(text)
    out = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", out)
    out = re.sub(r"\*(.+?)\*", r"<i>\1</i>", out)
    return out


def swatches(text: str, colors: dict) -> str:
    """Put a small colour square before each word in `colors` (e.g. Blue, Red)."""
    for word, color in colors.items():
        text = text.replace(f"<b>{word}</b>", f'<span class="sw" style="background:{color}"></span><b>{word}</b>')
    return text


def hero(eyebrow: str, title: str, body: str, chips: list) -> None:
    chip_html = "".join(f'<span class="chip">{c}</span>' for c in chips)
    st.markdown(
        f'<div class="hero"><div class="eyebrow">{eyebrow}</div><h1>{title}</h1>'
        f'<p>{body}</p><div class="chips">{chip_html}</div></div>',
        unsafe_allow_html=True,
    )


def ticker_header(symbol: str, meta_html: str) -> None:
    st.markdown(
        f'<div class="ticker"><span class="sym">{html.escape(symbol)}</span>'
        f'<span class="meta">{meta_html}</span></div>',
        unsafe_allow_html=True,
    )


def period_pill(text: str) -> None:
    st.markdown(f'<span class="period">{html.escape(text)}</span>', unsafe_allow_html=True)


def section(number, title: str, what: str, how: str, colors: dict = None):
    """A bordered card with a numbered header and a what/how description.
    Returns the card container so the chart can be placed inside it."""
    card = st.container(border=True)
    desc = (
        f'<span class="k">What it shows:</span> {_md_inline(what)}<br>'
        f'<span class="k">How to read it:</span> {_md_inline(how)}'
    )
    if colors:
        desc = swatches(desc, colors)
    card.markdown(
        f'<div class="sec"><div class="num">{number}</div><div><h4>{html.escape(title)}</h4>'
        f'<div class="desc">{desc}</div></div></div>',
        unsafe_allow_html=True,
    )
    return card
