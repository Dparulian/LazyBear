"""Sumber data dashboard: Supabase (produksi) atau folder output/ (mode lokal hasil --dry-run)."""
from __future__ import annotations

from pathlib import Path

import pandas as pd
import streamlit as st
import yfinance as yf

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "output"


def _secret(key: str):
    try:
        return st.secrets.get(key)
    except Exception:  # noqa: BLE001 - secrets.toml tidak ada
        return None


def mode() -> str:
    return "supabase" if _secret("SUPABASE_URL") and _secret("SUPABASE_ANON_KEY") else "local"


@st.cache_resource
def _client():
    from supabase import create_client

    return create_client(_secret("SUPABASE_URL"), _secret("SUPABASE_ANON_KEY"))


@st.cache_data(ttl=600, show_spinner=False)
def list_runs() -> pd.DataFrame:
    if mode() == "supabase":
        data = (
            _client().table("screening_runs").select("*").eq("status", "success")
            .order("run_date", desc=True).limit(250).execute().data
        )
        df = pd.DataFrame(data)
    else:
        rows = []
        for p in sorted(OUT.glob("results_*.csv"), reverse=True):
            r = pd.read_csv(p)
            rows.append({"run_date": p.stem.split("_")[1], "passed_count": len(r),
                         "new_count": int((r.get("status") == "BARU").sum()) if len(r) else 0})
        df = pd.DataFrame(rows)
    if not df.empty:
        df["run_date"] = pd.to_datetime(df["run_date"]).dt.date
    return df


@st.cache_data(ttl=600, show_spinner=False)
def get_results(run_date) -> pd.DataFrame:
    if mode() == "supabase":
        rows, start = [], 0
        while True:
            chunk = (
                _client().table("screening_results").select("*")
                .eq("run_date", str(run_date)).range(start, start + 999).execute().data
            )
            rows += chunk
            if len(chunk) < 1000:
                break
            start += 1000
        df = pd.DataFrame(rows)
    else:
        p = OUT / f"results_{run_date}.csv"
        df = pd.read_csv(p) if p.exists() else pd.DataFrame()
    if df.empty:
        return df
    for c in ("close", "change_pct", "sma20", "ema50", "spread_pct", "macd", "macd_signal",
              "macd_hist", "avg_value_20d", "days_since_cross", "streak", "volume"):
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce")
    return df


@st.cache_data(ttl=3600, show_spinner=False)
def get_prices(ticker: str, period: str = "1y") -> pd.DataFrame:
    """Harga harian dari Yahoo Finance. Ambil ekstra 1 tahun agar EMA50 & MACD sudah 'panas'."""
    warmup = {"6mo": "2y", "1y": "2y", "2y": "5y", "5y": "max"}.get(period, "2y")
    df = yf.download(f"{ticker}.JK", period=warmup, interval="1d", auto_adjust=False,
                     actions=False, progress=False, threads=False)
    if df is None or df.empty:
        return pd.DataFrame()
    if isinstance(df.columns, pd.MultiIndex):  # (Price, Ticker) atau (Ticker, Price)
        lvl = 0 if "Close" in df.columns.get_level_values(0) else 1
        df.columns = df.columns.get_level_values(lvl)
    df.index = pd.to_datetime(df.index).tz_localize(None)
    return df[["Open", "High", "Low", "Close", "Volume"]].dropna(subset=["Close"])
