"""Kondisi pasar: indikator IHSG (^JKSE) + lampu HIJAU / KUNING / MERAH dari 3 pemicu.

Pemicu (hasil evaluasi 25 Sep – 13 Nov 2026: pola momentum memberi 61% kena +10% di fase
naik, tetapi hanya 16% di fase crash):
  1. Tren IHSG   : close di atas SMA20 dan EMA50, MACD > 0.
  2. Breadth     : jumlah saham yang lolos screener naik dibanding N hari bursa lalu.
  3. Pola terbaik: minimal REGIME_MIN_BEST saham memenuhi pola terbaik hari itu.

HIJAU = 3 pemicu, KUNING = 2 pemicu, MERAH = 0–1 pemicu.
"""
from __future__ import annotations

import logging
import time
from datetime import date

import pandas as pd
import yfinance as yf

from .config import CONFIG, ScreenerConfig
from .indicators import add_indicators

log = logging.getLogger(__name__)

MARKET_COLUMNS = [
    "run_date", "index_symbol", "close", "change_pct", "sma20", "ema50", "macd", "macd_signal", "macd_hist",
    "above_sma20", "above_ema50", "macd_positive", "trend_score",
    "passed_count", "passed_count_prev", "breadth_up", "best_count", "best_ok",
    "triggers", "regime", "note",
]


def download_index(cfg: ScreenerConfig = CONFIG) -> pd.DataFrame:
    """OHLCV harian indeks (default ^JKSE). DataFrame kosong bila gagal."""
    for attempt in range(1, cfg.max_retries + 1):
        try:
            df = yf.download(cfg.index_symbol, period=cfg.history_period, interval="1d",
                             auto_adjust=False, actions=False, progress=False, threads=False)
            if df is None or df.empty:
                raise RuntimeError("data kosong")
            if isinstance(df.columns, pd.MultiIndex):
                lvl = 0 if "Close" in df.columns.get_level_values(0) else 1
                df.columns = df.columns.get_level_values(lvl)
            df = df[["Open", "High", "Low", "Close", "Volume"]].dropna(subset=["Close"])
            df.index = pd.to_datetime(df.index).tz_localize(None)
            return df.sort_index()
        except Exception as exc:  # noqa: BLE001
            log.warning("Unduh %s gagal (percobaan %d): %s", cfg.index_symbol, attempt, exc)
            time.sleep(3 * attempt)
    return pd.DataFrame()


def index_metrics(index_df: pd.DataFrame, as_of: date, cfg: ScreenerConfig = CONFIG) -> dict | None:
    """Indikator IHSG pada tanggal `as_of` (bar terakhir <= as_of)."""
    if index_df is None or index_df.empty:
        return None
    df = index_df[index_df.index <= pd.Timestamp(as_of)]
    if len(df) < cfg.ema_period + 5:
        return None
    ind = add_indicators(df, cfg)
    last, prev = ind.iloc[-1], ind.iloc[-2]
    if pd.isna(last["sma"]) or pd.isna(last["ema"]) or pd.isna(last["macd"]):
        return None
    close = float(last["Close"])
    above_sma, above_ema, macd_pos = close > last["sma"], close > last["ema"], last["macd"] > 0
    return {
        "index_date": ind.index[-1].date(),
        "close": close,
        "change_pct": (close / float(prev["Close"]) - 1) * 100,
        "sma20": float(last["sma"]), "ema50": float(last["ema"]),
        "macd": float(last["macd"]), "macd_signal": float(last["macd_signal"]), "macd_hist": float(last["macd_hist"]),
        "above_sma20": bool(above_sma), "above_ema50": bool(above_ema), "macd_positive": bool(macd_pos),
        "trend_score": int(above_sma) + int(above_ema) + int(macd_pos),
    }


def regime(idx: dict | None, passed_count: int, passed_count_prev: int | None, best_count: int,
           cfg: ScreenerConfig = CONFIG) -> dict:
    """Gabungkan 3 pemicu menjadi lampu pasar."""
    t1 = bool(idx and idx["trend_score"] == 3)
    t2 = passed_count_prev is not None and passed_count > passed_count_prev
    t3 = best_count >= cfg.regime_min_best
    n = int(t1) + int(t2) + int(t3)
    reg = "HIJAU" if n == 3 else ("KUNING" if n == 2 else "MERAH")
    notes = []
    if idx is None:
        notes.append("data IHSG tidak tersedia")
    elif not t1:
        miss = [k for k, ok in (("SMA20", idx["above_sma20"]), ("EMA50", idx["above_ema50"]),
                                ("MACD>0", idx["macd_positive"])) if not ok]
        notes.append("IHSG gagal: " + ", ".join(miss))
    if passed_count_prev is None:
        notes.append("breadth: belum ada pembanding")
    elif not t2:
        notes.append(f"breadth turun/datar ({passed_count_prev}→{passed_count})")
    if not t3:
        notes.append(f"pola terbaik {best_count} < {cfg.regime_min_best}")
    return {"trend_ok": t1, "breadth_up": bool(t2), "best_ok": t3, "triggers": n, "regime": reg,
            "note": "; ".join(notes) or "semua pemicu terpenuhi"}


def market_row(as_of: date, idx: dict | None, reg: dict, passed_count: int, passed_count_prev: int | None,
               best_count: int, cfg: ScreenerConfig = CONFIG) -> dict:
    row = {c: None for c in MARKET_COLUMNS}
    row.update({"run_date": as_of, "index_symbol": cfg.index_symbol, "passed_count": passed_count,
                "passed_count_prev": passed_count_prev, "best_count": best_count})
    if idx:
        row.update({k: idx[k] for k in ("close", "change_pct", "sma20", "ema50", "macd", "macd_signal", "macd_hist",
                                        "above_sma20", "above_ema50", "macd_positive", "trend_score")})
    row.update({k: reg[k] for k in ("breadth_up", "best_ok", "triggers", "regime", "note")})
    return row
