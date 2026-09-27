"""Konfigurasi screener. Semua nilai bisa di-override lewat environment variable."""
from __future__ import annotations

import os
from dataclasses import dataclass


def _env_int(name: str, default: int) -> int:
    return int(os.getenv(name, default))


def _env_float(name: str, default: float) -> float:
    return float(os.getenv(name, default))


@dataclass(frozen=True)
class ScreenerConfig:
    # --- Indikator ---
    sma_period: int = _env_int("SMA_PERIOD", 20)
    ema_period: int = _env_int("EMA_PERIOD", 50)
    macd_fast: int = _env_int("MACD_FAST", 12)
    macd_slow: int = _env_int("MACD_SLOW", 26)
    macd_signal: int = _env_int("MACD_SIGNAL", 9)

    # --- Aturan sinyal ---
    # Jendela ENTRY: MACD harus > 0 dalam N hari bursa sejak golden cross SMA20 > EMA50.
    # Setelah entry, saham tetap lolos selama SMA20 > EMA50 dan MACD > 0 (tanpa batas hari).
    cross_lookback: int = _env_int("CROSS_LOOKBACK", 5)

    # --- Filter likuiditas ---
    liquidity_window: int = _env_int("LIQUIDITY_WINDOW", 20)
    min_avg_value_idr: float = _env_float("MIN_AVG_VALUE_IDR", 1_000_000_000)  # Rp1 miliar / hari
    min_price: float = _env_float("MIN_PRICE", 50)

    # --- Data ---
    history_period: str = os.getenv("HISTORY_PERIOD", "1y")
    min_bars: int = _env_int("MIN_BARS", 120)
    batch_size: int = _env_int("BATCH_SIZE", 80)
    batch_pause_sec: float = _env_float("BATCH_PAUSE_SEC", 2.0)
    max_retries: int = _env_int("MAX_RETRIES", 3)


CONFIG = ScreenerConfig()

YAHOO_SUFFIX = ".JK"
UNCLASSIFIED = "Belum Terklasifikasi"

# Label sektor Yahoo (GICS-like) -> Bahasa Indonesia, hanya untuk tampilan.
SECTOR_LABEL_ID = {
    "Basic Materials": "Bahan Baku",
    "Communication Services": "Infrastruktur & Komunikasi",
    "Consumer Cyclical": "Konsumen Siklikal",
    "Consumer Defensive": "Konsumen Non-Siklikal",
    "Energy": "Energi",
    "Financial Services": "Keuangan",
    "Healthcare": "Kesehatan",
    "Industrials": "Perindustrian",
    "Real Estate": "Properti & Real Estat",
    "Technology": "Teknologi",
    "Utilities": "Utilitas",
}


def sector_label(sector: str | None) -> str:
    if not sector:
        return UNCLASSIFIED
    return SECTOR_LABEL_ID.get(sector, sector)


def to_yahoo(ticker: str) -> str:
    t = ticker.strip().upper()
    return t if t.endswith(YAHOO_SUFFIX) else f"{t}{YAHOO_SUFFIX}"


def from_yahoo(symbol: str) -> str:
    s = symbol.strip().upper()
    return s[: -len(YAHOO_SUFFIX)] if s.endswith(YAHOO_SUFFIX) else s
