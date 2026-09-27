from datetime import date

import numpy as np
import pandas as pd
import pytest

from screener.config import ScreenerConfig
from screener.indicators import add_indicators, ema, sma
from screener.run_screener import screen_universe
from screener.signals import assign_status, evaluate_stock, last_cross_up, sort_by_industry, trend_entry

CFG = ScreenerConfig(min_avg_value_idr=1e9, min_price=50, min_bars=120, cross_lookback=5)


def make_prices(n=260, seed=1, start=1000.0, volume=5_000_000):
    """Turun 150 hari lalu naik -> menghasilkan golden cross SMA20/EMA50 di paruh akhir."""
    rng = np.random.default_rng(seed)
    drift = np.r_[np.full(150, -0.002), np.full(n - 150, 0.004)]
    close = start * np.exp(np.cumsum(drift + rng.normal(0, 0.004, n)))
    idx = pd.bdate_range("2025-01-01", periods=n)
    return pd.DataFrame(
        {"Open": close, "High": close * 1.01, "Low": close * 0.99, "Close": close,
         "Volume": np.full(n, volume)},
        index=idx,
    )


def cut_after_cross(df, days_after):
    ind = add_indicators(df, CFG)
    pos = last_cross_up(ind["sma"], ind["ema"])
    # cross pertama setelah fase naik dimulai
    diff = (ind["sma"] - ind["ema"])
    crosses = np.flatnonzero(((diff > 0) & (diff.shift(1) <= 0)).to_numpy())
    first_up = [c for c in crosses if c > 150][0]
    return df.iloc[: first_up + days_after + 1], first_up


def test_indicator_basics():
    s = pd.Series(np.arange(1, 101, dtype=float))
    assert sma(s, 20).iloc[-1] == pytest.approx(np.mean(np.arange(81, 101)))
    assert np.isnan(sma(s, 20).iloc[18])
    assert ema(s, 50).iloc[-1] < s.iloc[-1]


def test_last_cross_up():
    a = pd.Series([1, 2, 3, 2, 1, 2, 3.0])
    assert last_cross_up(a, 2.5) == 6
    assert last_cross_up(a, 10.0) is None


@pytest.mark.parametrize("days_after", [0, 4, 5, 20, 60])
def test_stays_while_trend_valid(days_after):
    """Tidak ada batas hari: tetap lolos selama SMA20 > EMA50 dan MACD > 0 sejak entry."""
    df, _ = cut_after_cross(make_prices(), days_after)
    m = evaluate_stock(df, CFG)
    assert m is not None
    assert m["days_since_cross"] == days_after
    assert m["sma20"] > m["ema50"] and m["macd"] > 0  # fase naik
    assert m["passed"] is True
    assert m["entry_date"] is not None


def S(vals):
    return pd.Series(vals, dtype=float)


def test_trend_entry_rules():
    #            0    1    2    3    4    5    6    7
    sma = S([1.0, 1.0, 2.0, 2.0, 2.0, 2.0, 2.0, 2.0])
    ema = S([1.5] * 8)                         # golden cross di bar 2
    # MACD naik di atas 0 di bar 4 (dalam jendela 5 bar) dan bertahan -> valid, walau cross 5 bar lalu
    ok = S([-2, -1, -1, -0.5, 0.2, 0.5, 0.8, 1.0])
    assert trend_entry(sma, ema, ok, 5) == (2, 4, True)
    # MACD sempat di bawah 0 setelah entry -> keluar
    dip = S([-2, -1, -1, -0.5, 0.2, -0.1, 0.8, 1.0])
    assert trend_entry(sma, ema, dip, 5) == (2, 4, False)
    # MACD baru > 0 setelah jendela entry (bar 7 = 5 bar setelah cross) -> tidak pernah entry
    late = S([-2, -1, -1, -1, -1, -1, -1, 0.3])
    assert trend_entry(sma, ema, late, 5) == (2, None, False)
    # SMA turun ke bawah EMA -> keluar
    sma_dn = S([1.0, 1.0, 2.0, 2.0, 2.0, 2.0, 2.0, 1.0])
    assert trend_entry(sma_dn, ema, ok, 5)[2] is False


def test_illiquid_is_rejected():
    df, _ = cut_after_cross(make_prices(volume=100), 1)
    m = evaluate_stock(df, CFG)
    assert m["trend_valid"] and not m["is_liquid"] and not m["passed"]


def test_macd_below_zero_rejected():
    df, _ = cut_after_cross(make_prices(), 1)
    m = evaluate_stock(df, CFG)
    assert m["macd_state"] in {"CROSS_UP_0", "ABOVE_0"}
    down = make_prices()
    down["Close"] = 1000 * np.exp(np.linspace(0, -0.8, len(down)))  # tren turun murni
    m2 = evaluate_stock(down, CFG)
    assert m2["macd"] < 0 and not m2["passed"]


def test_insufficient_history():
    assert evaluate_stock(make_prices().iloc[:100], CFG) is None


def test_assign_status_new_vs_still():
    cur = pd.DataFrame({"ticker": ["AAAA", "BBBB"]})
    prev = pd.DataFrame({"ticker": ["BBBB", "CCCC"], "streak": [3, 1],
                         "first_passed_date": ["2025-06-02", "2025-06-04"]})
    out = assign_status(cur, prev, date(2025, 6, 5)).set_index("ticker")
    assert out.loc["AAAA", "status"] == "BARU" and out.loc["AAAA", "streak"] == 1
    assert out.loc["BBBB", "status"] == "MASIH" and out.loc["BBBB", "streak"] == 4
    assert out.loc["BBBB", "first_passed_date"] == "2025-06-02"
    first = assign_status(cur, None, date(2025, 6, 5))
    assert set(first["status"]) == {"BARU"}


def test_screen_universe_and_sort():
    base, _ = cut_after_cross(make_prices(seed=1), 2)
    as_of = base.index[-1].date()
    prices = {
        "AAAA": base,
        "BBBB": base * 1.0,
        "ZZZZ": base.iloc[:-1],  # data basi / suspensi
    }
    uni = pd.DataFrame({"ticker": ["AAAA", "BBBB", "ZZZZ"], "name": ["A", "B", "Z"],
                        "sector": ["Energy", "Basic Materials", "Energy"],
                        "industry": ["Coal", "Gold", "Coal"]})
    passed, stats = screen_universe(prices, uni, as_of, CFG)
    assert stats["stale"] == 1
    assert set(passed["ticker"]) == {"AAAA", "BBBB"}
    passed = sort_by_industry(assign_status(passed, None, as_of))
    assert list(passed["sector"]) == ["Basic Materials", "Energy"]
