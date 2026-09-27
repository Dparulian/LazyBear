"""Logika kriteria screening dan penentuan status BARU / MASIH."""
from __future__ import annotations

import math
from datetime import date

import numpy as np
import pandas as pd

from .config import CONFIG, ScreenerConfig
from .indicators import add_indicators


def last_cross_up(fast: pd.Series, slow: pd.Series | float) -> int | None:
    """Posisi (integer) bar terakhir saat `fast` memotong ke atas `slow`.

    Cross di bar i: fast[i-1] <= slow[i-1] dan fast[i] > slow[i]. Bar dengan NaN diabaikan.
    """
    diff = fast - slow
    prev = diff.shift(1)
    mask = (diff > 0) & (prev <= 0) & diff.notna() & prev.notna()
    pos = np.flatnonzero(mask.to_numpy())
    return int(pos[-1]) if len(pos) else None


def trend_entry(
    sma: pd.Series, ema: pd.Series, macd: pd.Series, lookback: int
) -> tuple[int | None, int | None, bool]:
    """Cek apakah setup golden cross masih valid (stateless, dihitung dari histori harga).

    Aturan:
      * ENTRY  : golden cross SMA>EMA di bar c, lalu MACD > 0 pada salah satu bar c .. c+lookback-1.
                 Bar pertama yang memenuhi = bar entry e.
      * BERTAHAN: sejak cross SMA tetap di atas EMA (otomatis benar jika SMA>EMA hari ini, karena
                 c adalah cross terakhir) DAN MACD > 0 di SETIAP bar sejak e sampai hari ini.
      * KELUAR : SMA turun ke bawah EMA, atau MACD sempat < 0 setelah entry.

    Return (posisi cross, posisi entry, masih_valid).
    """
    cross_pos = last_cross_up(sma, ema)
    if cross_pos is None or not (sma.iloc[-1] > ema.iloc[-1]):
        return cross_pos, None, False
    window = macd.iloc[cross_pos : cross_pos + lookback].to_numpy()
    hits = np.flatnonzero(window > 0)
    if not len(hits):
        return cross_pos, None, False
    entry_pos = cross_pos + int(hits[0])
    still_valid = bool((macd.iloc[entry_pos:] > 0).all())
    return cross_pos, entry_pos, still_valid


def evaluate_stock(df: pd.DataFrame, cfg: ScreenerConfig = CONFIG) -> dict | None:
    """Hitung metrik satu saham. Return None jika data tidak cukup.

    df: DataFrame harian dengan index tanggal naik dan kolom Open, High, Low, Close, Volume.
    """
    df = df.dropna(subset=["Close"])
    df = df[df["Close"] > 0]
    if len(df) < cfg.min_bars:
        return None

    ind = add_indicators(df, cfg)
    last = ind.iloc[-1]
    if any(pd.isna(last[c]) for c in ("sma", "ema", "macd", "macd_signal")):
        return None

    n = len(ind)
    idx = ind.index
    close = float(last["Close"])
    prev_close = float(ind["Close"].iloc[-2])

    # --- Likuiditas ---
    value = (ind["Close"] * ind["Volume"].fillna(0)).tail(cfg.liquidity_window)
    avg_value = float(value.mean())
    is_liquid = avg_value >= cfg.min_avg_value_idr and close >= cfg.min_price

    # --- Golden cross SMA20 di atas EMA50 ---
    cross_pos, entry_pos, trend_valid = trend_entry(
        ind["sma"], ind["ema"], ind["macd"], cfg.cross_lookback
    )
    days_since_cross = (n - 1 - cross_pos) if cross_pos is not None else None

    # --- MACD crossing di atas 0 atau sudah di atas 0 ---
    macd_val = float(last["macd"])
    macd_above_zero = macd_val > 0
    macd_pos = last_cross_up(ind["macd"], 0.0)
    macd_days = (n - 1 - macd_pos) if macd_pos is not None else None
    if not macd_above_zero:
        macd_state = "BELOW_0"
    elif macd_days is not None and macd_days < cfg.cross_lookback:
        macd_state = "CROSS_UP_0"  # baru saja menembus garis nol
    else:
        macd_state = "ABOVE_0"  # sudah bertahan di atas garis nol

    passed = bool(trend_valid and is_liquid)

    return {
        "last_date": idx[-1].date() if hasattr(idx[-1], "date") else idx[-1],
        "close": close,
        "change_pct": (close / prev_close - 1) * 100 if prev_close else None,
        "sma20": float(last["sma"]),
        "ema50": float(last["ema"]),
        "spread_pct": (float(last["sma"]) / float(last["ema"]) - 1) * 100,
        "macd": macd_val,
        "macd_signal": float(last["macd_signal"]),
        "macd_hist": float(last["macd_hist"]),
        "macd_state": macd_state,
        "macd_cross_date": _pos_date(idx, macd_pos),
        "cross_date": _pos_date(idx, cross_pos),
        "days_since_cross": days_since_cross,
        "volume": int(last["Volume"]) if not pd.isna(last["Volume"]) else None,
        "avg_value_20d": avg_value,
        "entry_date": _pos_date(idx, entry_pos),
        "is_liquid": bool(is_liquid),
        "trend_valid": bool(trend_valid),
        "passed": passed,
    }


def _pos_date(idx: pd.Index, pos: int | None):
    if pos is None:
        return None
    d = idx[pos]
    return d.date() if hasattr(d, "date") else d


def assign_status(
    current: pd.DataFrame, previous: pd.DataFrame | None, run_date: date
) -> pd.DataFrame:
    """Beri label BARU / MASIH dengan membandingkan ke hasil run sebelumnya.

    current : saham yang lolos hari ini (kolom 'ticker' wajib)
    previous: hasil lolos run sebelumnya (kolom ticker, streak, first_passed_date) atau None
    """
    out = current.copy()
    if previous is None or previous.empty:
        prev_map: dict = {}
    else:
        prev_map = previous.set_index("ticker")[["streak", "first_passed_date"]].to_dict("index")

    status, streak, first = [], [], []
    for t in out["ticker"]:
        p = prev_map.get(t)
        if p is None:
            status.append("BARU")
            streak.append(1)
            first.append(run_date)
        else:
            status.append("MASIH")
            prev_streak = p.get("streak")
            streak.append(int(prev_streak) + 1 if _is_num(prev_streak) else 2)
            first.append(p.get("first_passed_date") or run_date)
    out["status"] = status
    out["streak"] = streak
    out["first_passed_date"] = first
    return out


def _is_num(x) -> bool:
    try:
        return x is not None and not math.isnan(float(x))
    except (TypeError, ValueError):
        return False


def sort_by_industry(df: pd.DataFrame) -> pd.DataFrame:
    """Urutan akhir: sektor -> industri -> BARU dulu -> nilai transaksi terbesar."""
    if df.empty:
        return df
    tmp = df.copy()
    tmp["_status_rank"] = tmp["status"].map({"BARU": 0, "MASIH": 1}).fillna(2)
    tmp = tmp.sort_values(
        ["sector", "industry", "_status_rank", "avg_value_20d"],
        ascending=[True, True, True, False],
        na_position="last",
    )
    return tmp.drop(columns="_status_rank").reset_index(drop=True)
