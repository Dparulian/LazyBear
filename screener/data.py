"""Pengambilan data harga harian dari Yahoo Finance (via yfinance)."""
from __future__ import annotations

import logging
import time
from collections import Counter

import pandas as pd
import yfinance as yf

from .config import CONFIG, ScreenerConfig, from_yahoo, to_yahoo

log = logging.getLogger(__name__)
FIELDS = ["Open", "High", "Low", "Close", "Volume"]


def _split_download(raw: pd.DataFrame, symbols: list[str]) -> dict[str, pd.DataFrame]:
    out: dict[str, pd.DataFrame] = {}
    if raw is None or raw.empty:
        return out
    if isinstance(raw.columns, pd.MultiIndex):
        level0 = set(raw.columns.get_level_values(0))
        for sym in symbols:
            if sym not in level0:
                continue
            df = raw[sym]
            df = df[[c for c in FIELDS if c in df.columns]].dropna(how="all")
            if not df.empty:
                out[sym] = df
    elif len(symbols) == 1:
        df = raw[[c for c in FIELDS if c in raw.columns]].dropna(how="all")
        if not df.empty:
            out[symbols[0]] = df
    return out


def download_prices(
    tickers: list[str], cfg: ScreenerConfig = CONFIG
) -> dict[str, pd.DataFrame]:
    """Download OHLCV harian untuk daftar ticker IDX (tanpa .JK). Return {ticker: df}."""
    symbols = [to_yahoo(t) for t in tickers]
    result: dict[str, pd.DataFrame] = {}
    for i in range(0, len(symbols), cfg.batch_size):
        batch = symbols[i : i + cfg.batch_size]
        for attempt in range(1, cfg.max_retries + 1):
            try:
                raw = yf.download(
                    batch,
                    period=cfg.history_period,
                    interval="1d",
                    group_by="ticker",
                    auto_adjust=False,
                    actions=False,
                    threads=True,
                    progress=False,
                )
                got = _split_download(raw, batch)
                break
            except Exception as exc:  # noqa: BLE001 - yfinance melempar bermacam error
                wait = 5 * attempt
                log.warning("Batch %s gagal (percobaan %s): %s; tunggu %ss", i, attempt, exc, wait)
                time.sleep(wait)
                got = {}
        for sym, df in got.items():
            df.index = pd.to_datetime(df.index).tz_localize(None)
            result[from_yahoo(sym)] = df.sort_index()
        log.info("Batch %d-%d: %d/%d ticker ada data", i, i + len(batch), len(got), len(batch))
        time.sleep(cfg.batch_pause_sec)
    return result


def infer_as_of_date(prices: dict[str, pd.DataFrame]):
    """Tanggal bursa terakhir = tanggal bar terakhir yang paling umum di seluruh universe."""
    last_dates = [df.dropna(subset=["Close"]).index[-1].date() for df in prices.values() if not df.dropna(subset=["Close"]).empty]
    if not last_dates:
        return None
    return Counter(last_dates).most_common(1)[0][0]
