"""Recurring Investment Simulator — Streamlit UI.

Pick a ticker, run every recurring-buy schedule against its history, compare
total returns, and collect tickers into a portfolio for side-by-side comparison.

Run with:  .venv/bin/streamlit run app.py
"""
import io

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from data import load_prices, saved_tickers
from schedule import GROUPS, ORDINALS, WEEKDAYS, all_configs, config_by_label
from simulate import (
    build_buys,
    complete_months,
    leaderboard,
    rolling,
    rolling_summary,
    value_curve,
)
from ui import hero, inject_css, period_pill, section, ticker_header

st.set_page_config(page_title="Recurring Investment Simulator", page_icon="📈", layout="wide")
inject_css()

CONFIGS = all_configs()

# The app ships a dark theme (.streamlit/config.toml). Data colours follow the reference
# palette's dark steps (dataviz skill): categorical slots in fixed order, blue<->red diverging
# with a neutral midpoint. Blue = better than the typical schedule, red = worse.
SERIES = ["#3987e5", "#d95926", "#199e70", "#c98500"]
BETTER, WORSE = "#3987e5", "#e66767"
MIDDLE = "#3a3f55"
DIVERGING = [[0, WORSE], [0.5, MIDDLE], [1, BETTER]]
HEAT_COLORS = {"Blue": BETTER, "red": WORSE, "grey": MIDDLE}
ACCENT = BETTER
MUTED = "#8a93b5"
GRID = "rgba(255,255,255,0.07)"


# ---------------------------------------------------------------- cached computation
@st.cache_data(show_spinner=False, ttl="6h")  # expires so a failed live download is retried later
def cached_prices(ticker: str, refresh_token: int) -> pd.DataFrame:
    return load_prices(ticker, refresh=refresh_token > 0)


@st.cache_data(show_spinner=False)
def cached_leaderboard(ticker, prices, budget, start, end, fill, fee):
    return leaderboard(prices, CONFIGS, budget, start, end, fill, fee)


@st.cache_data(show_spinner=False)
def cached_rolling(ticker, prices, budget, window, first, last, fill, fee):
    return rolling(prices, CONFIGS, budget, window, first, last, fill, fee)


def money(x: float) -> str:
    return f"-${-x:,.2f}" if x < 0 else f"${x:,.2f}"


def fmt_month(p: pd.Period) -> str:
    return p.strftime("%b %Y")


def clamp_period(want_start, want_end, months):
    """Fit the requested period inside `months`; returns (start, end) or None."""
    start, end = max(want_start, months[0]), min(want_end, months[-1])
    return (start, end) if start < end else None


# ---------------------------------------------------------------- layout helpers
def style_fig(fig: go.Figure, height: int = 380) -> go.Figure:
    fig.update_layout(
        height=height, margin=dict(l=10, r=10, t=10, b=10), hovermode="closest",
        font=dict(size=12, family="Inter, system-ui, sans-serif"),
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        hoverlabel=dict(bgcolor="#141b33", bordercolor="#2f3a63", font=dict(color="#e7ecff")),
    )
    fig.update_xaxes(gridcolor=GRID, zeroline=False)
    fig.update_yaxes(gridcolor=GRID, zeroline=False)
    return fig


# ---------------------------------------------------------------- charts
GRID_ROWS = (
    [("Daily", lambda w: "Daily")]  # same value in every column; shown for side-by-side comparison
    + [("Weekly", lambda w: f"Weekly · {WEEKDAYS[w]}")]
    + [(f"Bi-weekly ({p})", lambda w, p=p: f"Bi-weekly · {WEEKDAYS[w]} ({p})") for p in "AB"]
    + [(f"Monthly {ORDINALS[n]}", lambda w, n=n: f"Monthly · {ORDINALS[n]} {WEEKDAYS[w]}") for n in range(1, 5)]
)


def goodness(values: pd.Series) -> pd.Series:
    """Map values to [-1, 1]: 0 = the median schedule, +1 = best, -1 = worst (symmetric
    around the median so the gray midpoint always means 'typical')."""
    centred = values - values.median()
    bound = centred.abs().max() or 1
    return centred / bound


def frequency_strip(values: pd.Series, hover: pd.Series, y_title: str) -> go.Figure:
    """Every schedule as a dot, grouped by frequency."""
    fig = go.Figure()
    for group in GROUPS:
        labels = [c.label for c in CONFIGS if c.group == group]
        fig.add_trace(
            go.Box(
                y=[values[l] for l in labels], name=group, boxpoints="all", jitter=0.45, pointpos=0,
                fillcolor="rgba(0,0,0,0)", line=dict(color="rgba(0,0,0,0)"),
                marker=dict(color=ACCENT, size=9),
                customdata=[[l, hover[l]] for l in labels],
                hovertemplate="<b>%{customdata[0]}</b><br>%{customdata[1]}<extra></extra>",
                showlegend=False,
            )
        )
    fig.update_yaxes(title=y_title, ticksuffix="%")
    return style_fig(fig, 400)


def weekday_heatmap(values: pd.Series, text: pd.Series) -> go.Figure:
    """Rows = frequency, columns = weekday. Colour is relative to the median of all 64
    schedules, shared with the day-of-month chart."""
    g = goodness(values)
    z = [[g[fn(w)] for w in range(5)] for _, fn in GRID_ROWS]
    txt = [[text[fn(w)] for w in range(5)] for _, fn in GRID_ROWS]
    hover = [[fn(w) for w in range(5)] for _, fn in GRID_ROWS]
    fig = go.Figure(
        go.Heatmap(
            z=z,
            x=WEEKDAYS,
            y=[name for name, _ in GRID_ROWS],
            text=txt,
            customdata=hover,
            texttemplate="%{text}",
            textfont=dict(size=13),
            hovertemplate="<b>%{customdata}</b><br>%{text}<extra></extra>",
            colorscale=DIVERGING,
            zmin=-1,
            zmax=1,
            xgap=3,
            ygap=3,
            colorbar=dict(
                tickvals=[-1, 0, 1], ticktext=["Worse", "Typical", "Better"],
                thickness=12, len=0.9, outlinewidth=0, tickfont=dict(size=12),
            ),
        )
    )
    fig.update_yaxes(autorange="reversed", tickfont=dict(size=13))
    fig.update_xaxes(side="top", tickfont=dict(size=13))
    return style_fig(fig, 560)


def dom_dots(values: pd.Series, hover: pd.Series, y_title: str, reference: float) -> go.Figure:
    """Monthly-on-a-fixed-date schedules as dots (no zero baseline needed, so small
    differences stay visible). Colours match the heatmap."""
    days = list(range(1, 29))
    labels = [f"Monthly · day {d}" for d in days]
    g = goodness(values)
    fig = go.Figure(
        go.Scatter(
            x=days,
            y=[values[l] for l in labels],
            mode="markers",
            marker=dict(size=11, color=[g[l] for l in labels], colorscale=DIVERGING, cmin=-1, cmax=1,
                        line=dict(width=1, color=MUTED)),
            customdata=[hover[l] for l in labels],
            hovertemplate="<b>Day %{x}</b><br>%{customdata}<extra></extra>",
            showlegend=False,
        )
    )
    fig.add_hline(y=reference, line_dash="dot", line_color=MUTED,
                  annotation_text="Daily", annotation_position="top right")
    fig.update_xaxes(title="Day of month", dtick=1)
    fig.update_yaxes(title=y_title, ticksuffix="%")
    return style_fig(fig, 380)


def line_chart(series: dict, y_title: str, zero_line: bool = False) -> go.Figure:
    fig = go.Figure()
    for i, (label, s) in enumerate(series.items()):
        fig.add_trace(
            go.Scatter(
                x=s.index, y=s.values, name=label, mode="lines",
                line=dict(color=SERIES[i], width=2),
                hovertemplate=label + ": %{y:.2f}<extra></extra>",
            )
        )
    if zero_line:
        fig.add_hline(y=0, line_color=MUTED, line_dash="dot")
    fig.update_layout(hovermode="x unified", legend=dict(orientation="h", y=1.08, x=0))
    fig.update_yaxes(title=y_title)
    return style_fig(fig, 420)


def featured(labels_in_order) -> list:
    """Up to four distinct schedules for line charts, in fixed colour order."""
    return list(dict.fromkeys(labels_in_order))[:4]


# ---------------------------------------------------------------- session state
if "portfolio" not in st.session_state:
    st.session_state.portfolio = {}  # ticker -> monthly budget
if "refresh" not in st.session_state:
    st.session_state.refresh = 0

# ---------------------------------------------------------------- sidebar
with st.sidebar:
    st.markdown('<div class="side-brand">Recurring Investment Simulator</div>', unsafe_allow_html=True)
    st.header("Inputs")
    ticker = st.text_input(
        "Ticker", "VOO",
        help="Any symbol on Yahoo Finance: stocks, ETFs, mutual funds. "
             f"Saved prices are always available for {', '.join(saved_tickers())}.",
    ).strip().upper()
    budget = st.number_input("Monthly budget ($)", min_value=1.0, value=1000.0, step=50.0)
    # Fixed month list (not derived from the ticker) so the selection survives ticker changes.
    last_month = pd.Timestamp.today().to_period("M") - 1
    month_opts = [str(m) for m in pd.period_range("2000-01", last_month, freq="M")]
    start_s, end_s = st.select_slider(
        "Time period of simulation",
        help="Whole months. Used by the Single period and Portfolio tabs; Rolling windows always use full history.",
        options=month_opts,
        value=(month_opts[-36], month_opts[-1]),
        format_func=lambda s: fmt_month(pd.Period(s, "M")),
        key="period",
    )
    want_start, want_end = pd.Period(start_s, "M"), pd.Period(end_s, "M")
    fill = st.radio("Buy at", ["close", "open"], horizontal=True, format_func=str.title)
    fee = st.number_input("Fee per trade ($)", min_value=0.0, value=0.0, step=0.5)
    st.caption(
        "Every schedule invests the same monthly budget, split evenly across that month's buys. "
        "Prices are dividend-adjusted (dividends reinvested). Fractional shares."
    )
    if st.button("Re-download price data"):
        st.session_state.refresh += 1
        st.cache_data.clear()

hero(
    "Backtest your auto-invest",
    "Recurring Investment Simulator",
    "Daily, weekly, bi-weekly or monthly? Monday or Friday? The 1st or the 15th? "
    "Replay every recurring-buy schedule against real price history and see which one would have "
    "grown your money the most. New here? Open the <b>Read me</b> tab.",
    ["<b>64</b> schedules", "<b>Any</b> stock, ETF or fund", "<b>Rolling</b> backtests", "Dividends reinvested"],
)

if not ticker:
    st.info("Enter a ticker in the sidebar.")
    st.stop()

try:
    with st.spinner(f"Loading {ticker}…"):
        prices = cached_prices(ticker, st.session_state.refresh)
except Exception as e:  # noqa: BLE001 - surface any download problem to the user
    st.error(f"Could not load {ticker}: {e}")
    st.stop()

months = complete_months(prices)
last_day = prices.index[-1]
if last_day < pd.Timestamp.today().normalize() - pd.Timedelta(days=7):
    st.info(f"Using saved prices for {ticker}, which end on {last_day.strftime('%d %b %Y')}. "
            "Click **Re-download price data** in the sidebar to try fetching the latest.")
if len(months) < 2:
    st.error(f"{ticker} does not have enough price history yet.")
    st.stop()

# Header row: ticker + add-to-portfolio.
head, action = st.columns([4, 1], vertical_alignment="center")
last_close = prices["close"].iloc[-1]
year_ago = prices["adj_close"][prices.index <= prices.index[-1] - pd.DateOffset(years=1)]
yoy = (prices["adj_close"].iloc[-1] / year_ago.iloc[-1] - 1) * 100 if len(year_ago) else None
yoy_html = (f' · <span class="{"up" if yoy >= 0 else "down"}">{"▲" if yoy >= 0 else "▼"} {abs(yoy):.1f}%</span> 1y'
            if yoy is not None else "")
with head:
    ticker_header(
        ticker,
        f"<b>{money(last_close)}</b> last close{yoy_html} · investing <b>{money(budget)}</b>/month"
        f" · history since {prices.index[0].strftime('%b %Y')}",
    )
in_portfolio = st.session_state.portfolio.get(ticker) == budget
if action.button(
    "✓ In portfolio" if in_portfolio else "＋ Add to portfolio",
    disabled=in_portfolio,
    width="stretch",
    help="Saves this ticker and monthly budget to the Portfolio tab.",
):
    st.session_state.portfolio[ticker] = budget
    st.rerun()

tab_single, tab_roll, tab_port, tab_readme = st.tabs(["Single period", "Rolling windows", "Portfolio", "Read me"])

# ---------------------------------------------------------------- single period
with tab_single:
    period = clamp_period(want_start, want_end, months)
    if period is None:
        st.error(f"{ticker} only has data for {fmt_month(months[0])} – {fmt_month(months[-1])}. "
                 "Pick a period in that range.")
    else:
        start, end = period
        if period != (want_start, want_end):
            st.info(f"Period shortened to {fmt_month(start)} – {fmt_month(end)}, the range {ticker} has data for.")
        lb = cached_leaderboard(ticker, prices, budget, start, end, fill, fee)
        by_label = lb.set_index("config")
        ret = by_label["return_pct"]
        cell_text = by_label.apply(lambda r: f"{r['return_pct']:.2f}%<br>{money(r['final_value'])}", axis=1)
        hover_text = by_label.apply(lambda r: f"{r['return_pct']:.2f}% · {money(r['final_value'])}", axis=1)

        period_pill(f"{fmt_month(start)} – {fmt_month(end)}")
        best, worst = lb.iloc[0], lb.iloc[-1]
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Invested", money(best["invested"]))
        c2.metric(f"Best: {best['config']}", money(best["final_value"]), f"{best['return_pct']:.2f}% return")
        c3.metric(f"Worst: {worst['config']}", money(worst["final_value"]), f"{worst['return_pct']:.2f}% return",
                  delta_color="off")
        c4.metric("Best − worst", money(best["final_value"] - worst["final_value"]),
                  f"{best['return_pct'] - worst['return_pct']:.2f} pp", delta_color="off")
        st.caption(
            "Under a fixed monthly budget, buying early in the month gets the money invested sooner. "
            "In a rising market that alone favours early-month schedules, separately from any weekday effect."
        )

        card = section(
            1, "Total return of every schedule, by frequency",
            "Each dot is one of the 64 schedules, grouped by how often it buys.",
            "Higher is better. A tight cluster means the day you pick within that frequency barely matters; "
            "a wide spread means it does. Hover over a dot to see which schedule it is.",
        )
        card.plotly_chart(frequency_strip(ret, hover_text, "Total return (%)"), key="s_strip")

        card = section(
            2, "Total return by frequency and weekday",
            "Each cell is one schedule: the row is how often it buys, the column is the weekday it buys on. "
            "Cells show total return and final account value.",
            "**Blue** = better than the typical (median) schedule, **red** = worse, **grey** = about typical; "
            "darker means further from typical. *Daily* is the same in every column. *Bi-weekly A/B* are the two "
            "alternating sets of weeks. *Monthly 2nd* + *Tue* means the 2nd Tuesday of every month.",
            colors=HEAT_COLORS,
        )
        card.plotly_chart(weekday_heatmap(ret, cell_text), key="s_heat")

        card = section(
            3, "Monthly on a fixed date: total return",
            "The 28 schedules that buy once a month on a calendar date (the 1st … the 28th). "
            "If the market is closed that day, the buy happens on the next trading day.",
            "Each dot is one date; higher is better. Colours match the grid above. "
            "The dotted line marks Daily for reference.",
        )
        card.plotly_chart(dom_dots(ret, hover_text, "Total return (%)", ret["Daily"]), key="s_dom")

        best_weekly = lb[lb["group"] == "Weekly"].iloc[0]["config"]
        show = featured([best["config"], "Daily", best_weekly, worst["config"]])
        curves = {}
        for label in show:
            curve = value_curve(build_buys(config_by_label(label), prices, budget, fill, fee),
                                prices, start, end, budget)
            curves[label] = (curve["value"] / curve["contributed"] - 1) * 100
        card = section(
            4, "Total return over time",
            "Running total return (account value ÷ money put in so far) for the best schedule, Daily, "
            "the best weekly day, and the worst schedule. Money not yet invested in a month counts as cash.",
            "Lines close together mean the schedule made little difference; the gap at the right edge is the "
            "final difference. Early on the lines jump around because little money is invested yet.",
        )
        card.plotly_chart(line_chart(curves, "Total return (%)"), key="s_line")

        with st.expander(f"Full results table ({len(lb)} schedules)"):
            st.dataframe(
                lb[["rank", "config", "group", "final_value", "profit", "return_pct", "xirr_pct",
                    "avg_cost", "trades", "first_buy"]],
                hide_index=True,
                width="stretch",
                column_config={
                    "rank": st.column_config.NumberColumn("#"),
                    "config": "Schedule",
                    "group": "Frequency",
                    "final_value": st.column_config.NumberColumn("Final value", format="$%.2f"),
                    "profit": st.column_config.NumberColumn("Profit", format="$%.2f"),
                    "return_pct": st.column_config.NumberColumn("Total return %", format="%.2f"),
                    "xirr_pct": st.column_config.NumberColumn("Annualised (XIRR) %", format="%.2f"),
                    "avg_cost": st.column_config.NumberColumn("Avg cost/share (div-adj.)", format="$%.2f"),
                    "trades": "Buys",
                    "first_buy": st.column_config.DateColumn("First buy"),
                },
            )
            st.caption("'First buy' shows which weeks Bi-weekly A and B use.")

# ---------------------------------------------------------------- rolling
with tab_roll:
    st.markdown(
        "A single period is one draw of luck. Here every schedule is replayed over **every** window of the "
        "chosen length across the ticker's full history, sliding forward one month at a time "
        "(Jan–Dec, Feb–Jan, Mar–Feb, …). Each schedule's **median** return across all those windows shows "
        "how it does *typically*, not just once."
    )
    window = st.slider("Window length (months)", 6, 60, 24, step=6, key="window")
    if len(months) < window:
        st.warning(f"{ticker} does not have enough history for {window}-month windows.")
    else:
        with st.spinner("Running rolling windows…"):
            roll = cached_rolling(ticker, prices, budget, window, months[0], months[-1], fill, fee)
        summary = rolling_summary(roll)
        by_label = summary.set_index("config")
        med = by_label["median_return_pct"]
        n_win = roll["window_start"].nunique()
        cell_text = med.map(lambda v: f"{v:.2f}%")
        hover_text = by_label.apply(
            lambda r: f"median {r['median_return_pct']:.2f}% · top-10% finish in {r['top10_pct']:.0f}% of windows",
            axis=1,
        )

        period_pill(f"{n_win} windows of {window} months · {fmt_month(months[0])} – {fmt_month(months[-1])}")
        top, bottom = summary.iloc[0], summary.iloc[-1]
        c1, c2, c3 = st.columns(3)
        c1.metric(f"Best typical: {top['config']}", f"{top['median_return_pct']:.2f}%", "median return",
                  delta_color="off")
        c2.metric(f"Worst typical: {bottom['config']}", f"{bottom['median_return_pct']:.2f}%", "median return",
                  delta_color="off")
        c3.metric(f"{top['config']} finished in the top 10%", f"{top['top10_pct']:.0f}% of windows")

        card = section(
            1, "Median total return of every schedule, by frequency",
            f"Each dot is one schedule's median total return across all {n_win} windows, grouped by frequency.",
            "Higher is better. A tight cluster means the day you pick within that frequency barely matters. "
            "Hover over a dot to see the schedule and how often it finished in the top 10%.",
        )
        card.plotly_chart(frequency_strip(med, hover_text, "Median total return (%)"), key="r_strip")

        card = section(
            2, "Median total return by frequency and weekday",
            "Same grid as the single-period tab, but each cell is the schedule's median return across all windows.",
            "**Blue** = better than the typical schedule, **red** = worse, **grey** = about typical. A row that is "
            "blue here was reliably good, not just lucky once.",
            colors=HEAT_COLORS,
        )
        card.plotly_chart(weekday_heatmap(med, cell_text), key="r_heat")

        card = section(
            3, "Monthly on a fixed date: median total return",
            "The 28 calendar-date schedules, each as its median return across all windows.",
            "Higher is better; colours match the grid. The dotted line marks Daily.",
        )
        card.plotly_chart(dom_dots(med, hover_text, "Median total return (%)", med["Daily"]), key="r_dom")

        best_weekly = summary[summary["group"] == "Weekly"].iloc[0]["config"]
        show = featured([top["config"], best_weekly, bottom["config"]])
        pivot = roll.pivot(index="window_start", columns="config", values="return_pct")
        pivot.index = pivot.index.to_timestamp()
        gaps = {label: pivot[label] - pivot["Daily"] for label in show if label != "Daily"}
        card = section(
            4, "Advantage over investing daily, window by window",
            "For each window (plotted at the month it starts), the schedule's total return minus Daily's total "
            "return in that same window, in percentage points. Shown for the best typical schedule, the best "
            "weekly day and the worst typical schedule.",
            "Above the dotted zero line = beat Daily in that window; below = trailed it. A line that stays above "
            "zero is a consistent edge; one that crosses back and forth is mostly luck.",
        )
        card.plotly_chart(line_chart(gaps, "vs Daily (pp)", zero_line=True), key="r_line")

        with st.expander("Rolling summary table"):
            st.dataframe(
                summary.drop(columns=["avg_rank"]), hide_index=True, width="stretch",
                column_config={
                    "config": "Schedule",
                    "group": "Frequency",
                    "median_return_pct": st.column_config.NumberColumn("Median total return %", format="%.2f"),
                    "mean_return_pct": st.column_config.NumberColumn("Mean total return %", format="%.2f"),
                    "worst_return_pct": st.column_config.NumberColumn("Worst window %", format="%.2f"),
                    "best_return_pct": st.column_config.NumberColumn("Best window %", format="%.2f"),
                    "top10_pct": st.column_config.NumberColumn("Top-10% finishes (% of windows)", format="%.0f"),
                },
            )

# ---------------------------------------------------------------- portfolio
with tab_port:
    pf = st.session_state.portfolio
    st.info(
        "Compare several tickers side by side: while researching a ticker, click **＋ Add to portfolio** "
        "(next to the ticker name above) to add it here with its monthly budget. Repeat for each ticker "
        "you want to compare."
    )

    left, right = st.columns(2)
    with right:
        uploaded = st.file_uploader("Load a saved portfolio (CSV)", type="csv", key="pf_upload")
        if uploaded is not None and st.session_state.get("pf_upload_id") != uploaded.file_id:
            try:
                loaded = pd.read_csv(uploaded)
                for _, row in loaded.iterrows():
                    pf[str(row["ticker"]).strip().upper()] = float(row["monthly_budget"])
                st.session_state.pf_upload_id = uploaded.file_id
                st.rerun()
            except Exception as e:  # noqa: BLE001
                st.error(f"Could not read that file (expected columns: ticker, monthly_budget): {e}")
    with left:
        st.markdown("**Holdings**")
        if not pf:
            st.caption("Empty. Research a ticker and click **＋ Add to portfolio** above.")
        for t, b in list(pf.items()):
            c_name, c_btn = st.columns([4, 1], vertical_alignment="center")
            c_name.markdown(f"{t} · {money(b)}/month")
            if c_btn.button("Remove", key=f"rm_{t}"):
                del pf[t]
                st.rerun()
        if pf:
            csv = pd.DataFrame({"ticker": list(pf), "monthly_budget": list(pf.values())}).to_csv(index=False)
            st.download_button("Download portfolio (CSV)", csv, "portfolio.csv", "text/csv")

    if pf:
        holdings = {}
        for t in pf:
            try:
                holdings[t] = cached_prices(t, st.session_state.refresh)
            except Exception as e:  # noqa: BLE001
                st.error(f"Could not load {t}: {e}")
        common = sorted(set.intersection(*(set(complete_months(p)) for p in holdings.values()))) if holdings else []
        period = clamp_period(want_start, want_end, common) if len(common) >= 2 else None
        if period is None:
            st.error("The holdings don't share enough price history for the selected period.")
        else:
            start, end = period
            st.divider()
            period_pill(f"{fmt_month(start)} – {fmt_month(end)}"
                        + (" · shortened to the range all holdings have data for"
                           if period != (want_start, want_end) else ""))

            results = {t: cached_leaderboard(t, p, pf[t], start, end, fill, fee) for t, p in holdings.items()}
            window = st.session_state.get("window", 24)
            rows = []
            for t, lb in results.items():
                best, worst = lb.iloc[0], lb.iloc[-1]
                daily = lb.set_index("config").loc["Daily"]
                row = {
                    "Ticker": t, "Monthly budget": pf[t], "Invested": best["invested"],
                    "Best schedule": best["config"], "Best return %": best["return_pct"],
                    "Daily return %": daily["return_pct"],
                    "Worst schedule": worst["config"], "Worst return %": worst["return_pct"],
                }
                m = complete_months(holdings[t])
                if len(m) >= window:
                    r = rolling_summary(cached_rolling(t, holdings[t], pf[t], window, m[0], m[-1], fill, fee))
                    row[f"Best typical ({window}-mo rolling)"] = r.iloc[0]["config"]
                rows.append(row)
            table = pd.DataFrame(rows)

            # Portfolio-level result if every holding followed the same schedule.
            combined = pd.concat(results.values()).groupby("config")[["invested", "final_value"]].sum()
            combined["return_pct"] = (combined["final_value"] / combined["invested"] - 1) * 100
            best_each = sum(lb.iloc[0]["final_value"] for lb in results.values())
            invested = combined["invested"].iloc[0]

            c1, c2, c3 = st.columns(3)
            c1.metric("Total invested", money(invested))
            c2.metric("Each holding on its best schedule", money(best_each),
                      f"{(best_each / invested - 1) * 100:.2f}% return")
            c3.metric("Everything on Daily", money(combined.at["Daily", "final_value"]),
                      f"{combined.at['Daily', 'return_pct']:.2f}% return", delta_color="off")

            st.markdown("#### Holdings compared")
            st.dataframe(
                table, hide_index=True, width="stretch",
                column_config={
                    "Monthly budget": st.column_config.NumberColumn(format="$%.0f"),
                    "Invested": st.column_config.NumberColumn(format="$%.2f"),
                    "Best return %": st.column_config.NumberColumn(format="%.2f"),
                    "Daily return %": st.column_config.NumberColumn(format="%.2f"),
                    "Worst return %": st.column_config.NumberColumn(format="%.2f"),
                },
            )

            card = section(
                1, "Range of outcomes per holding",
                "For each holding, every one of the 64 schedules as a dot (total return over the single period).",
                "Compare how high each holding sits (the asset's performance) with how tall its column of dots is "
                "(how much the schedule mattered for it). Hover over a dot for the schedule.",
            )
            fig = go.Figure()
            for t, lb in results.items():
                fig.add_trace(go.Box(
                    y=lb["return_pct"], name=t, boxpoints="all", jitter=0.45, pointpos=0,
                    fillcolor="rgba(0,0,0,0)", line=dict(color="rgba(0,0,0,0)"),
                    marker=dict(color=ACCENT, size=9), customdata=lb[["config"]].values,
                    hovertemplate="<b>%{customdata[0]}</b><br>%{y:.2f}%<extra></extra>", showlegend=False,
                ))
            fig.update_yaxes(title="Total return (%)", ticksuffix="%")
            card.plotly_chart(style_fig(fig, 400), key="p_strip")

            if len(results) > 1:
                ptext = combined.apply(lambda r: f"{r['return_pct']:.2f}%<br>{money(r['final_value'])}", axis=1)
                card = section(
                    2, "Whole portfolio if every holding used the same schedule",
                    "Each cell is the combined portfolio's total return and final value if all holdings bought on "
                    "that schedule.",
                    "**Blue** = better than the typical schedule, **red** = worse. Useful if you'd rather keep one "
                    "schedule for everything.",
                    colors=HEAT_COLORS,
                )
                card.plotly_chart(weekday_heatmap(combined["return_pct"], ptext), key="p_heat")

# ---------------------------------------------------------------- read me
with tab_readme:
    st.markdown(
        """
### What this tool is for

You've decided to invest a fixed amount every month in something (say $1,000 in an index fund).
You still have to choose **how to spread it**:

- **How often** to buy: daily, weekly, every two weeks, or once a month?
- **On which day**: which weekday, or which date of the month? Once you pick a day, it stays fixed.

This tool answers that with history rather than guesswork. It replays **64 schedules** against the
ticker's real prices and shows how each one would have turned out. Every schedule invests exactly the
same amount each month, so the only difference between them is *when* the money goes in.

### How to use it

1. **Enter a ticker** in the sidebar: any stock, ETF or mutual fund on Yahoo Finance (e.g. VOO, QQQ, AAPL).
2. **Set your monthly budget** and the **time period of simulation**.
3. **Single period** tab: see how every schedule did over that period. Start with the heatmap (chart 2).
   Blue cells did better than the typical schedule, red cells worse.
4. **Rolling windows** tab: check whether the winner is reliable. The same test is repeated over every
   window of the chosen length (e.g. every 24-month stretch) in the ticker's history. A schedule that is
   blue here wins *consistently*, not just once. **Base your decision on this tab.**
5. **Portfolio** tab: click **＋ Add to portfolio** for each ticker you research, then compare them
   side by side. You can download the portfolio as CSV and load it back later.

### The 64 schedules

| Frequency | Variations | Count |
|---|---|---|
| Daily | every trading day | 1 |
| Weekly | Mon, Tue, Wed, Thu or Fri | 5 |
| Bi-weekly | each weekday × two alternating week sets (A / B) | 10 |
| Monthly (Nth weekday) | 1st, 2nd, 3rd or 4th Mon–Fri of the month (e.g. "2nd Tuesday") | 20 |
| Monthly (date) | the 1st … 28th of the month | 28 |

### Rules of the simulation

- **Same budget for every schedule.** Each month's budget is split evenly across that month's buys
  (e.g. $1,000 over 4 Tuesdays = $250 each; over 5 Tuesdays = $200 each).
- **Market holidays.** If a buy falls on a day the market is closed, it happens on the next trading day.
- **Dividends are reinvested** (prices are dividend-adjusted). Fractional shares are allowed.
- **Buy at** the day's close (default) or open. An optional **fee per trade** penalises frequent buying.
- **Not included:** taxes, bid/ask spreads and intraday timing.

### What to expect

- **The differences are usually small,** often a fraction of a percent. That is a useful answer in
  itself: if all the schedules end up close, pick whatever is convenient.
- **Buying early in the month tends to win** under a fixed monthly budget, because the money gets
  invested sooner and markets have risen more often than not. That effect is usually bigger than any
  weekday effect.
- **Single-period winners can be luck.** If a schedule wins one period but not across rolling windows,
  don't rely on it.

### Data & disclaimer

Prices come from Yahoo Finance (via the open-source `yfinance` library) and are cached on this computer,
so results are reproducible; use **Re-download price data** to refresh them. This tool is for education
and research only. It is not financial advice, and past performance does not guarantee future results.
"""
    )

st.divider()
st.caption(
    "Data: Yahoo Finance via yfinance, cached locally. Simulations are deterministic replays of history and "
    "ignore taxes, bid/ask spreads and order timing within the day. Not financial advice."
)
