"""Bangun / perbarui daftar saham IDX + sektor & industri ke tabel `stocks`.

Sumber:
  1. Yahoo Finance equity screener (exchange = JKT)  -> daftar ticker
  2. yfinance Ticker.info                            -> nama, sektor, industri
  3. data/sector_override.csv (opsional)             -> timpa sektor/industri, mis. klasifikasi IDX-IC

Jalankan:  python -m screener.build_universe            (hanya ambil info untuk ticker baru)
           python -m screener.build_universe --full     (ambil ulang info semua ticker)
           python -m screener.build_universe --dry-run  (tulis ke output/universe.csv, tanpa Supabase)
"""
from __future__ import annotations

import argparse
import logging
import time
from pathlib import Path

import pandas as pd
import yfinance as yf

from . import db
from .config import from_yahoo, to_yahoo

log = logging.getLogger("build_universe")
ROOT = Path(__file__).resolve().parents[1]
SEED = ROOT / "data" / "universe_seed.csv"
OVERRIDE = ROOT / "data" / "sector_override.csv"


def fetch_idx_symbols() -> pd.DataFrame:
    """Semua saham di bursa Jakarta menurut Yahoo screener (dipaginasi 250 per halaman)."""
    from yfinance import EquityQuery

    query = EquityQuery("eq", ["exchange", "JKT"])
    rows, offset = [], 0
    while True:
        res = yf.screen(query, offset=offset, size=250, sortField="ticker", sortAsc=True)
        quotes = res.get("quotes", [])
        for q in quotes:
            sym = q.get("symbol", "")
            if sym.endswith(".JK"):
                rows.append({"ticker": from_yahoo(sym), "name": q.get("longName") or q.get("shortName")})
        total = res.get("total", 0)
        offset += len(quotes)
        if not quotes or offset >= total:
            break
        time.sleep(1)
    return pd.DataFrame(rows).drop_duplicates("ticker")


def fetch_info(ticker: str) -> dict:
    try:
        info = yf.Ticker(to_yahoo(ticker)).info or {}
    except Exception as exc:  # noqa: BLE001
        log.warning("info %s gagal: %s", ticker, exc)
        return {}
    return {
        "name": info.get("longName") or info.get("shortName"),
        "sector": info.get("sector"),
        "industry": info.get("industry"),
    }


def apply_override(df: pd.DataFrame) -> pd.DataFrame:
    if not OVERRIDE.exists():
        return df
    ov = pd.read_csv(OVERRIDE, dtype=str).fillna("")
    ov["ticker"] = ov["ticker"].str.upper().str.strip()
    ov = ov.set_index("ticker")
    df = df.set_index("ticker")
    for col in ("sector", "industry"):
        if col in ov.columns:
            vals = ov[col].replace("", pd.NA).dropna()
            df.loc[df.index.intersection(vals.index), col] = vals
    df = df.reset_index()
    df.loc[df["ticker"].isin(ov.index), "source"] = "override"
    return df


def build(existing: pd.DataFrame, full: bool) -> pd.DataFrame:
    try:
        symbols = fetch_idx_symbols()
        log.info("Yahoo screener: %d ticker", len(symbols))
    except Exception as exc:  # noqa: BLE001
        log.error("Yahoo screener gagal (%s) — pakai seed %s", exc, SEED.name)
        symbols = pd.DataFrame()
    if symbols.empty:
        symbols = pd.read_csv(SEED, dtype=str)[["ticker"]].assign(name=None)

    known = existing.set_index("ticker") if not existing.empty else pd.DataFrame()
    rows = []
    for i, r in enumerate(symbols.itertuples(index=False), 1):
        t = r.ticker
        has = (not known.empty) and t in known.index and pd.notna(known.loc[t].get("sector"))
        if has and not full:
            k = known.loc[t]
            rows.append({"ticker": t, "name": k.get("name") or r.name, "sector": k.get("sector"),
                         "industry": k.get("industry")})
            continue
        info = fetch_info(t)
        rows.append({"ticker": t, "name": info.get("name") or r.name,
                     "sector": info.get("sector"), "industry": info.get("industry")})
        if i % 25 == 0:
            log.info("info %d/%d", i, len(symbols))
        time.sleep(0.3)

    out = pd.DataFrame(rows)
    out["source"] = "yahoo"
    out["is_active"] = True
    return apply_override(out)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--full", action="store_true", help="ambil ulang info semua ticker")
    ap.add_argument("--dry-run", action="store_true", help="tanpa Supabase, tulis ke output/")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    if args.dry_run:
        df = build(pd.DataFrame(), full=True)
        (ROOT / "output").mkdir(exist_ok=True)
        df.to_csv(ROOT / "output" / "universe.csv", index=False)
        log.info("Tersimpan output/universe.csv (%d ticker)", len(df))
        return

    client = db.get_client(write=True)
    existing = db.select_all(client, "stocks", "ticker,name,sector,industry")
    df = build(existing, full=args.full)

    # Nonaktifkan ticker yang hilang dari bursa (delisting) — hanya jika hasil fetch lengkap
    if not existing.empty and len(df) >= 0.8 * len(existing):
        gone = sorted(set(existing["ticker"]) - set(df["ticker"]))
        if gone:
            log.info("Nonaktifkan %d ticker: %s", len(gone), ", ".join(gone[:20]))
            db.upsert(client, "stocks", [{"ticker": t, "is_active": False} for t in gone], "ticker")

    cols = ["ticker", "name", "sector", "industry", "source", "is_active"]
    db.upsert(client, "stocks", db.records(df, cols), on_conflict="ticker")
    log.info("Upsert %d saham ke tabel stocks", len(df))


if __name__ == "__main__":
    main()
