"""Indikator teknikal murni pandas (tanpa dependensi TA-Lib)."""
from __future__ import annotations

import pandas as pd

from .config import CONFIG, ScreenerConfig


def sma(series: pd.Series, period: int) -> pd.Series:
    return series.rolling(period, min_periods=period).mean()


def ema(series: pd.Series, period: int) -> pd.Series:
    # adjust=False = rumus EMA standar yang dipakai TradingView / Stockbit
    return series.ewm(span=period, adjust=False, min_periods=period).mean()


def macd(series: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9):
    macd_line = ema(series, fast) - ema(series, slow)
    signal_line = macd_line.ewm(span=signal, adjust=False, min_periods=signal).mean()
    hist = macd_line - signal_line
    return macd_line, signal_line, hist


def add_indicators(df: pd.DataFrame, cfg: ScreenerConfig = CONFIG) -> pd.DataFrame:
    """Tambahkan kolom sma, ema, macd, macd_signal, macd_hist ke salinan df (butuh kolom Close)."""
    out = df.copy()
    close = out["Close"].astype(float)
    out["sma"] = sma(close, cfg.sma_period)
    out["ema"] = ema(close, cfg.ema_period)
    out["macd"], out["macd_signal"], out["macd_hist"] = macd(
        close, cfg.macd_fast, cfg.macd_slow, cfg.macd_signal
    )
    return out
