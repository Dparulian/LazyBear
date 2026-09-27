"""Job harian: SMA20 x EMA50 golden cross + MACD > 0 (bertahan selama tren valid) -> Supabase.

Jalankan:
  python -m screener.run_screener              # normal (GitHub Actions)
  python -m screener.run_screener --force      # tulis ulang run untuk tanggal yang sama
  python -m screener.run_screener --dry-run    # tanpa Supabase, hasil ke output/*.csv
"""
from __future__ import annotations

import argparse
import logging
import sys
from datetime import date, datetime, timezone
from pathlib import Path

import pandas as pd

from . import db
from .config import CONFIG, UNCLASSIFIED, ScreenerConfig
from .data import download_prices, infer_as_of_date
from .signals import assign_status, evaluate_stock, sort_by_industry

log = logging.getLogger("screener")
ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "output"

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


def run(dry_run: bool = False, force: bool = False, cfg: ScreenerConfig = CONFIG) -> pd.DataFrame:
    started = datetime.now(timezone.utc)
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
    as_of = infer_as_of_date(prices)
    log.info("Data harga: %d ticker, tanggal bursa terakhir %s", len(prices), as_of)

    if not dry_run and not force and db.run_exists(client, as_of):
        log.info("Run %s sudah ada (hari libur / job ganda) — dilewati.", as_of)
        return pd.DataFrame()

    run_row = {"run_date": as_of, "started_at": started.isoformat(), "status": "running",
               "universe_count": len(tickers), "downloaded_count": len(prices)}
    if client:
        db.save_run(client, run_row)

    try:
        # 3. Screening
        passed, stats = screen_universe(prices, universe, as_of, cfg)

        # 4. BARU vs MASIH (dibanding run sukses sebelumnya)
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
        log.info("Lolos: %d (BARU %d, MASIH %d) | keluar dari daftar: %d | pembanding: %s",
                 len(passed), n_new, len(passed) - n_new, len(exited), prev_date)

        # 5. Simpan
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
            db.replace_results(client, as_of, db.records(passed, RESULT_COLUMNS))
            db.save_run(client, run_row)
        return passed
    except Exception as exc:
        run_row.update({"status": "failed", "message": str(exc)[:500],
                        "finished_at": datetime.now(timezone.utc).isoformat()})
        if client:
            db.save_run(client, run_row)
        raise


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
