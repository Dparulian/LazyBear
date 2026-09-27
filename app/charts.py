"""Grafik Plotly untuk dashboard."""
from __future__ import annotations

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from screener.config import CONFIG
from screener.indicators import add_indicators

C = {
    "up": "#22c55e", "down": "#ef4444", "sma": "#f59e0b", "ema": "#38bdf8",
    "macd": "#a78bfa", "signal": "#f472b6", "grid": "rgba(148,163,184,0.12)",
    "baru": "#22c55e", "masih": "#3b82f6", "text": "#cbd5e1",
}
PERIOD_BARS = {"6mo": 126, "1y": 252, "2y": 504, "5y": 1260}


def _base_layout(fig: go.Figure, height: int):
    fig.update_layout(
        template="plotly_dark", height=height, margin=dict(l=10, r=10, t=30, b=10),
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        font=dict(color=C["text"], size=12), hovermode="x unified",
        legend=dict(orientation="h", yanchor="bottom", y=1.01, x=0, bgcolor="rgba(0,0,0,0)"),
    )
    fig.update_xaxes(gridcolor=C["grid"], showspikes=True, spikethickness=1)
    fig.update_yaxes(gridcolor=C["grid"])
    return fig


def technical_chart(prices: pd.DataFrame, ticker: str, period: str = "1y") -> go.Figure:
    ind = add_indicators(prices, CONFIG)
    diff = ind["sma"] - ind["ema"]
    cross_up = (diff > 0) & (diff.shift(1) <= 0)
    cross_dn = (diff < 0) & (diff.shift(1) >= 0)
    ind = ind.tail(PERIOD_BARS.get(period, 252))
    cross_up, cross_dn = cross_up.loc[ind.index], cross_dn.loc[ind.index]

    fig = make_subplots(rows=3, cols=1, shared_xaxes=True, vertical_spacing=0.03,
                        row_heights=[0.58, 0.14, 0.28],
                        subplot_titles=(None, None, f"MACD ({CONFIG.macd_fast},{CONFIG.macd_slow},{CONFIG.macd_signal})"))

    fig.add_trace(go.Candlestick(
        x=ind.index, open=ind["Open"], high=ind["High"], low=ind["Low"], close=ind["Close"],
        name=ticker, increasing_line_color=C["up"], decreasing_line_color=C["down"],
        increasing_fillcolor=C["up"], decreasing_fillcolor=C["down"], showlegend=False,
    ), row=1, col=1)
    fig.add_trace(go.Scatter(x=ind.index, y=ind["sma"], name=f"SMA {CONFIG.sma_period}",
                             line=dict(color=C["sma"], width=1.8)), row=1, col=1)
    fig.add_trace(go.Scatter(x=ind.index, y=ind["ema"], name=f"EMA {CONFIG.ema_period}",
                             line=dict(color=C["ema"], width=1.8)), row=1, col=1)

    up = ind[cross_up]
    dn = ind[cross_dn]
    fig.add_trace(go.Scatter(x=up.index, y=up["sma"] * 0.97, mode="markers", name="Golden cross",
                             marker=dict(symbol="triangle-up", size=13, color=C["up"],
                                         line=dict(color="white", width=1))), row=1, col=1)
    fig.add_trace(go.Scatter(x=dn.index, y=dn["sma"] * 1.03, mode="markers", name="Death cross",
                             marker=dict(symbol="triangle-down", size=11, color=C["down"])), row=1, col=1)
    if len(up):
        fig.add_vline(x=up.index[-1], line=dict(color=C["up"], dash="dot", width=1), row="all")

    vol_colors = np.where(ind["Close"] >= ind["Open"], C["up"], C["down"])
    fig.add_trace(go.Bar(x=ind.index, y=ind["Volume"], marker_color=vol_colors, opacity=0.6,
                         name="Volume", showlegend=False), row=2, col=1)

    hist_colors = np.where(ind["macd_hist"] >= 0, "rgba(34,197,94,0.55)", "rgba(239,68,68,0.55)")
    fig.add_trace(go.Bar(x=ind.index, y=ind["macd_hist"], marker_color=hist_colors,
                         name="Histogram", showlegend=False), row=3, col=1)
    fig.add_trace(go.Scatter(x=ind.index, y=ind["macd"], name="MACD",
                             line=dict(color=C["macd"], width=1.6)), row=3, col=1)
    fig.add_trace(go.Scatter(x=ind.index, y=ind["macd_signal"], name="Signal",
                             line=dict(color=C["signal"], width=1.2, dash="dot")), row=3, col=1)
    fig.add_hline(y=0, line=dict(color="rgba(226,232,240,0.6)", width=1, dash="dash"), row=3, col=1)

    # Sembunyikan akhir pekan & hari libur bursa
    all_days = pd.bdate_range(ind.index.min(), ind.index.max())
    holidays = all_days.difference(ind.index)
    fig.update_xaxes(rangebreaks=[dict(bounds=["sat", "mon"]), dict(values=list(holidays.strftime("%Y-%m-%d")))],
                     rangeslider_visible=False)
    fig.update_yaxes(title_text="Harga", row=1, col=1)
    fig.update_yaxes(title_text="Vol", row=2, col=1, showticklabels=False)
    return _base_layout(fig, 720)


def sector_bar(df: pd.DataFrame, label_col: str = "sector_label") -> go.Figure:
    g = (df.groupby([label_col, "status"]).size().unstack(fill_value=0)
         .reindex(columns=["BARU", "MASIH"], fill_value=0))
    g = g.assign(total=g.sum(axis=1)).sort_values("total")
    fig = go.Figure()
    fig.add_bar(y=g.index, x=g["BARU"], name="BARU", orientation="h", marker_color=C["baru"],
                text=g["BARU"].replace(0, ""), textposition="inside")
    fig.add_bar(y=g.index, x=g["MASIH"], name="MASIH", orientation="h", marker_color=C["masih"],
                text=g["MASIH"].replace(0, ""), textposition="inside")
    fig.update_layout(barmode="stack")
    _base_layout(fig, max(260, 36 * len(g) + 80))
    fig.update_layout(hovermode="y unified")
    fig.update_xaxes(title_text="Jumlah saham", dtick=1 if g["total"].max() <= 10 else None)
    return fig


def history_chart(runs: pd.DataFrame) -> go.Figure:
    r = runs.sort_values("run_date")
    fig = go.Figure()
    fig.add_bar(x=r["run_date"], y=r["new_count"], name="BARU", marker_color=C["baru"])
    fig.add_bar(x=r["run_date"], y=r["passed_count"] - r["new_count"], name="MASIH",
                marker_color=C["masih"])
    fig.update_layout(barmode="stack")
    fig.update_xaxes(type="category")
    return _base_layout(fig, 300)
