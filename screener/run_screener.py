"""Job harian: SMA20 x EMA50 golden cross + MACD > 0 (bertahan selama tren valid) -> Supabase.

Jalankan:
  python -m screener.run_screener              # normal (GitHub Actions)
  python -m screener.run_screener --force      # tetap tulis ulang walau unduhan lebih sedikit
  python -m screener.run_screener --dry-run    # tanpa Supabase, hasil ke output/*.csv

Perilaku tiap run:
  * Bar hari ini dibuang bila job berjalan sebelum 16:30 WIB (candle belum final).
  * Semua tanggal bursa SETELAH run sukses terakhir di-backfill (maks. MAX_BACKFILL_DAYS),
    jadi hari yang terlewat (Yahoo telat update, cron GitHub telat/terlewat) tetap tercatat.
  * Tanggal terakhir selalu dihitung ulang & ditimpa, sehingga run berikutnya di hari yang
    sama memperbaiki data yang belum lengkap. Overwrite dibatalkan bila unduhan jauh lebih sedikit.
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
from collections import Counter
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path

import pandas as pd

from . import db
from .config import CONFIG, UNCLASSIFIED, ScreenerConfig
from .data import download_prices
from .signals import assign_status, evaluate_stock, sort_by_industry

log = logging.getLogger("screener")
ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "output"
WIB = timezone(timedelta(hours=7))
MARKET_FINAL = time(16, 30)          # setelah jam ini candle harian IDX dianggap final
MAX_BACKFILL = int(os.getenv("MAX_BACKFILL_DAYS", "10"))

RESULT_COLUMNS = [
    "run_date", "ticker", "name", "sector", "industry", "status", "streak", "first_passed_date",
    "close", "change_pct", "sma20", "ema50", "spread_pct", "macd", "macd_signal", "macd_hist",
    "macd_state", "macd_cross_date", "cross_date", "entry_date", "days_since_cross", "volume", "avg_value_20d",
]


def screen_universe(
    prices: dict[str, pd.DataFrame],
    universe: pd.DataFrame,
    as_of: date,
    cfg: ScreenerConfig = CONFIG,
) -> tuple[pd.DataFrame, dict]:
    """Evaluasi semua saham. Return (saham yang lolos, statistik)."""
    meta = universe.set_index("ticker")
    rows, stats = [], {"evaluated": 0, "stale": 0, "insufficient": 0, "liquid": 0}
    for ticker, df in prices.items():
        m = evaluate_stock(df, cfg)
        if m is None:
            stats["insufficient"] += 1
            continue
        if m["last_date"] != as_of:  # suspensi / tidak ada transaksi hari ini
            stats["stale"] += 1
            continue
        stats["evaluated"] += 1
        stats["liquid"] += int(m["is_liquid"])
        if not m["passed"]:
            continue
        info = meta.loc[ticker] if ticker in meta.index else {}
        rows.append({
            "ticker": ticker,
            "name": _get(info, "name"),
            "sector": _get(info, "sector") or UNCLASSIFIED,
            "industry": _get(info, "industry") or UNCLASSIFIED,
            **{k: v for k, v in m.items() if k not in ("last_date", "is_liquid", "trend_valid", "passed")},
        })
    return pd.DataFrame(rows), stats


def _get(info, key):
    try:
        v = info[key]
    except (KeyError, TypeError):
        return None
    return None if pd.isna(v) else v


def load_universe_fallback() -> pd.DataFrame:
    for p in (OUT / "universe.csv", ROOT / "data" / "universe_seed.csv"):
        if p.exists():
            log.info("Universe dari %s", p.relative_to(ROOT))
            return pd.read_csv(p, dtype=str)
    raise SystemExit("Universe kosong. Jalankan dulu: python -m screener.build_universe")


def drop_incomplete_bar(prices: dict[str, pd.DataFrame], now_wib: datetime) -> tuple[dict, bool]:
    """Buang candle hari ini bila bursa belum tutup (run di jam bursa = data intraday)."""
    if now_wib.weekday() >= 5 or now_wib.time() >= MARKET_FINAL:
        return prices, False
    today = pd.Timestamp(now_wib.date())
    out = {t: df[df.index < today] for t, df in prices.items()}
    dropped = any(len(out[t]) != len(prices[t]) for t in prices)
    return {t: df for t, df in out.items() if not df.empty}, dropped


def trading_dates(prices: dict[str, pd.DataFrame]) -> list[date]:
    """Tanggal bursa = tanggal yang punya data di >= 30% saham (menyaring bar 'nyasar')."""
    cnt = Counter(d.date() for df in prices.values() for d in df.dropna(subset=["Close"]).index)
    thr = 0.3 * len(prices)
    return sorted(d for d, c in cnt.items() if c >= thr)


def expected_trading_day(now_wib: datetime) -> date:
    """Hari bursa terakhir yang seharusnya sudah final (tanpa memperhitungkan libur)."""
    d = now_wib.date()
    if now_wib.weekday() < 5 and now_wib.time() >= MARKET_FINAL:
        return d
    d -= timedelta(days=1)
    while d.weekday() >= 5:
        d -= timedelta(days=1)
    return d


def run(dry_run: bool = False, force: bool = False, cfg: ScreenerConfig = CONFIG,
        now: datetime | None = None) -> pd.DataFrame:
    now_wib = (now or datetime.now(timezone.utc)).astimezone(WIB)
    client = None if dry_run else db.get_client(write=True)

    # 1. Universe
    universe = pd.DataFrame() if dry_run else db.load_universe(client)
    if universe.empty:
        universe = load_universe_fallback()
    universe["ticker"] = universe["ticker"].str.upper().str.strip()
    tickers = sorted(universe["ticker"].unique())
    log.info("Universe: %d ticker", len(tickers))

    # 2. Harga
    prices = download_prices(tickers, cfg)
    if not prices:
        raise SystemExit("Tidak ada data harga dari Yahoo Finance.")
    prices, dropped = drop_incomplete_bar(prices, now_wib)
    if dropped:
        log.warning("Job berjalan %s WIB (sebelum %s) — candle hari ini dibuang karena belum final.",
                    now_wib.strftime("%H:%M"), MARKET_FINAL.strftime("%H:%M"))
    dates = trading_dates(prices)
    if not dates:
        raise SystemExit("Tidak ada tanggal bursa yang valid di data Yahoo.")
    as_of = dates[-1]
    expected = expected_trading_day(now_wib)
    log.info("Data harga: %d ticker, tanggal bursa terakhir %s (seharusnya >= %s)",
             len(prices), as_of, expected)
    if as_of < expected:
        log.warning("Yahoo Finance belum punya candle %s (terakhir %s). Jika bukan hari libur, "
                    "run berikutnya akan mem-backfill tanggal ini otomatis.", expected, as_of)

    # 3. Tentukan tanggal yang perlu dihitung: semua sesudah run sukses terakhir + tanggal terakhir
    last_ok = _last_ok_csv() if dry_run else db.last_success_date(client)
    if last_ok is None:
        targets = [as_of]
    else:
        targets = [d for d in dates if d > last_ok]
        if len(targets) > MAX_BACKFILL:
            log.warning("%d tanggal terlewat, hanya %d terakhir yang di-backfill.", len(targets), MAX_BACKFILL)
            targets = targets[-MAX_BACKFILL:]
        if not targets:
            targets = [as_of]  # tidak ada tanggal baru -> segarkan tanggal terakhir
    log.info("Run sukses terakhir: %s | tanggal diproses: %s", last_ok, ", ".join(map(str, targets)))

    result = pd.DataFrame()
    for d in targets:
        sliced = {t: df[df.index <= pd.Timestamp(d)] for t, df in prices.items()}
        sliced = {t: df for t, df in sliced.items() if not df.empty}
        result = run_one(client, d, sliced, universe, len(tickers), dry_run, force, cfg)
    return result


def run_one(client, as_of: date, prices: dict[str, pd.DataFrame], universe: pd.DataFrame,
            universe_count: int, dry_run: bool, force: bool, cfg: ScreenerConfig) -> pd.DataFrame:
    started = datetime.now(timezone.utc)
    n_have = sum(1 for df in prices.values() if df.index[-1].date() == as_of)

    if client and not force:
        existing = db.get_run(client, as_of)
        if existing and existing.get("status") == "success":
            prev_n = existing.get("downloaded_count") or 0
            if len(prices) < 0.9 * prev_n:
                log.warning("%s: unduhan sekarang %d ticker < 90%% dari run sebelumnya (%d) — "
                            "data lama dipertahankan.", as_of, len(prices), prev_n)
                return pd.DataFrame()
            log.info("%s sudah ada — dihitung ulang & ditimpa dengan data terbaru.", as_of)

    run_row = {"run_date": as_of, "started_at": started.isoformat(),
               "universe_count": universe_count, "downloaded_count": len(prices)}
    try:
        # Screening
        passed, stats = screen_universe(prices, universe, as_of, cfg)

        # BARU vs MASIH (dibanding run sukses sebelumnya)
        if dry_run:
            prev_date, prev = _prev_from_csv(as_of)
        else:
            prev_date, prev = db.previous_results(client, as_of)
        if not passed.empty:
            passed = assign_status(passed, prev, as_of)
            passed = sort_by_industry(passed)
        passed.insert(0, "run_date", as_of)
        exited = sorted(set(prev["ticker"]) - set(passed.get("ticker", []))) if not prev.empty else []

        n_new = int((passed.get("status") == "BARU").sum()) if not passed.empty else 0
        log.info("%s | Lolos: %d (BARU %d, MASIH %d) | keluar: %d | pembanding: %s | "
                 "ticker dgn candle tgl ini: %d",
                 as_of, len(passed), n_new, len(passed) - n_new, len(exited), prev_date, n_have)

        # Simpan: baris run (success) dulu karena FK, lalu hasil
        OUT.mkdir(exist_ok=True)
        passed.reindex(columns=RESULT_COLUMNS).to_csv(OUT / f"results_{as_of}.csv", index=False)
        run_row.update({
            "status": "success", "finished_at": datetime.now(timezone.utc).isoformat(),
            "liquid_count": stats["liquid"], "passed_count": len(passed), "new_count": n_new,
            "exited_count": len(exited),
            "message": f"evaluated={stats['evaluated']} stale={stats['stale']} "
                       f"insufficient={stats['insufficient']} prev={prev_date}",
        })
        if client:
            db.save_run(client, run_row)
            db.replace_results(client, as_of, db.records(passed, RESULT_COLUMNS))
        return passed
    except Exception as exc:
        run_row.update({"status": "failed", "message": str(exc)[:500],
                        "finished_at": datetime.now(timezone.utc).isoformat()})
        if client:
            try:
                db.save_run(client, run_row)
            except Exception:  # noqa: BLE001
                log.exception("Gagal mencatat status failed")
        raise


def _last_ok_csv():
    files = sorted(OUT.glob("results_*.csv"))
    return date.fromisoformat(files[-1].stem.split("_")[1]) if files else None


def _prev_from_csv(as_of: date):
    files = sorted(p for p in OUT.glob("results_*.csv") if p.stem.split("_")[1] < str(as_of))
    if not files:
        return None, pd.DataFrame(columns=["ticker"])
    p = files[-1]
    return p.stem.split("_")[1], pd.read_csv(p, dtype={"ticker": str})


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
                        stream=sys.stdout)
    res = run(dry_run=args.dry_run, force=args.force)
    if not res.empty:
        cols = ["status", "ticker", "sector", "industry", "close", "days_since_cross", "macd_state"]
        print(res[cols].to_string(index=False))


if __name__ == "__main__":
    main()
