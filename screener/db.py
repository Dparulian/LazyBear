"""Akses Supabase (Postgres) untuk screener."""
from __future__ import annotations

import math
import os
from datetime import date, datetime

import pandas as pd

PAGE = 1000


def get_client(write: bool = True):
    from supabase import create_client

    url = os.environ["SUPABASE_URL"]
    key = os.environ["SUPABASE_SERVICE_ROLE_KEY" if write else "SUPABASE_ANON_KEY"]
    return create_client(url, key)


def _clean(v):
    if v is None:
        return None
    if isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
        return None
    if isinstance(v, (pd.Timestamp, datetime)):
        return v.date().isoformat() if isinstance(v, pd.Timestamp) else v.isoformat()
    if isinstance(v, date):
        return v.isoformat()
    if hasattr(v, "item"):  # numpy scalar
        return _clean(v.item())
    return v


def records(df: pd.DataFrame, columns: list[str]) -> list[dict]:
    return [{c: _clean(r.get(c)) for c in columns} for r in df.to_dict("records")]


def select_all(client, table: str, columns: str = "*", **eq) -> pd.DataFrame:
    rows, start = [], 0
    while True:
        q = client.table(table).select(columns)
        for k, v in eq.items():
            q = q.eq(k, v)
        chunk = q.range(start, start + PAGE - 1).execute().data
        rows.extend(chunk)
        if len(chunk) < PAGE:
            break
        start += PAGE
    return pd.DataFrame(rows)


def upsert(client, table: str, rows: list[dict], on_conflict: str, chunk: int = 500):
    for i in range(0, len(rows), chunk):
        client.table(table).upsert(rows[i : i + chunk], on_conflict=on_conflict).execute()


# ---------- Query khusus ----------

def load_universe(client) -> pd.DataFrame:
    df = select_all(client, "stocks", "ticker,name,sector,industry,is_active")
    if df.empty:
        return df
    return df[df["is_active"].fillna(True)]


def get_run(client, run_date: date) -> dict | None:
    res = (
        client.table("screening_runs")
        .select("*")
        .eq("run_date", run_date.isoformat())
        .execute()
        .data
    )
    return res[0] if res else None


def last_success_date(client) -> date | None:
    res = (
        client.table("screening_runs")
        .select("run_date")
        .eq("status", "success")
        .order("run_date", desc=True)
        .limit(1)
        .execute()
        .data
    )
    return date.fromisoformat(res[0]["run_date"]) if res else None


def log_universe_run(client, row: dict):
    """Catat 1 eksekusi build_universe ke tabel universe_runs (best effort)."""
    client.table("universe_runs").insert({k: _clean(v) for k, v in row.items()}).execute()


def previous_results(client, run_date: date) -> tuple[date | None, pd.DataFrame]:
    res = (
        client.table("screening_runs")
        .select("run_date")
        .eq("status", "success")
        .lt("run_date", run_date.isoformat())
        .order("run_date", desc=True)
        .limit(1)
        .execute()
        .data
    )
    if not res:
        return None, pd.DataFrame()
    prev_date = date.fromisoformat(res[0]["run_date"])
    df = select_all(
        client, "screening_results", "ticker,streak,first_passed_date", run_date=prev_date.isoformat()
    )
    return prev_date, df


def replace_results(client, run_date: date, rows: list[dict]):
    client.table("screening_results").delete().eq("run_date", run_date.isoformat()).execute()
    if rows:
        upsert(client, "screening_results", rows, on_conflict="run_date,ticker")


def save_run(client, row: dict):
    upsert(client, "screening_runs", [{k: _clean(v) for k, v in row.items()}], on_conflict="run_date")
